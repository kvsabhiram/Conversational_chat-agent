# TECH_DOCS — Internal Technical Reference

A close-up look at every module, every input/output, every matching rule, and how the pieces talk to each other. Pair this with [REFERENCE_GUIDE.md](REFERENCE_GUIDE.md) for setup, usage, and troubleshooting.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Request Lifecycle (Every Step)](#2-request-lifecycle-every-step)
3. [Internal Call Graph](#3-internal-call-graph)
4. [Module Deep-Dive](#4-module-deep-dive)
5. [Data Shapes (All Schemas)](#5-data-shapes-all-schemas)
6. [Pattern Matching Internals](#6-pattern-matching-internals)
7. [Logging Specification](#7-logging-specification)
8. [Database Schema](#8-database-schema)
9. [Configuration Variables](#9-configuration-variables)
10. [Translation Pipeline Internals](#10-translation-pipeline-internals)

---

## 1. System Overview

A FastAPI service wrapping a local llama.cpp LLM with:
- **Multilingual I/O** via an IndicTrans2 translation gateway (auto-detect input, translate output to 30+ Indic / Roman variants).
- **6 sector personas** + a custom-persona engine (free-text → structured agent).
- **RAG** via per-sector ChromaDB collections.
- **Intent classification** via the same LLM with a JSON-extraction prompt.
- **Regex guardrails** for input attacks (prompt injection, harmful) and output PII.
- **Redis-backed session memory** (per chat, 24h TTL).
- **PostgreSQL conversation logs** + tri-destination logging (stdout, text file, JSON file).

External dependencies the app connects to:

| Dependency | Default Endpoint | Purpose | Failure Mode |
|---|---|---|---|
| llama.cpp | `http://localhost:8080` | LLM inference | Hard fail (503) on chat |
| IndicTrans2 gateway | `https://thousand-length-percentage-candle.trycloudflare.com` | Translation | Best-effort (passes original text) |
| Redis | `redis://localhost:6379/0` | Session memory | Empty history if disconnected |
| PostgreSQL | `postgresql+asyncpg://postgres:password@localhost:5432/chatagent` | Conversation logs | Best-effort (skip persistence) |
| ChromaDB | local `./data/chromadb` | Vector store | Empty RAG if not seeded |

---

## 2. Request Lifecycle (Every Step)

For `POST /api/chat`, the orchestrator is [`app/routers/chat.py`](app/routers/chat.py). Below is **every** transformation, in order.

### Inputs (the request body)

```json
{
  "message": "string (1..4000 chars, required)",
  "session_id": "string (optional; UUID generated if absent)",
  "sector": "retail|education|medical|real_estate|banking|tourism|custom_<id>",
  "tenant_id": "string (optional)",
  "src_lang": "auto | ENGLISH | HINDI | TELUGU | ... (default: auto)",
  "lang":     "ENGLISH | HINDI | HINDI_Latn | ... (default: ENGLISH)"
}
```

### Pipeline

| # | Step | Code | Input → Output | Notes |
|---|---|---|---|---|
| 1 | Sanitize | `helpers.sanitize_input` | `message` → trimmed, whitespace-collapsed, capped at 4000 chars | |
| 2 | Session ID | `helpers.generate_session_id` | `session_id or new UUID` | UUID4 hex |
| 3 | Translate input | `translator.to_english` | `(message, src_lang)` → English text | Skipped if `src_lang == ENGLISH`. Best-effort: returns original on failure |
| 4 | Input guardrails | `guardrails.check_input` | English text → `(blocked, reason)` | Regex match against injection + harmful patterns; 4000-char cap |
| 5 | Branch | `sector.startswith("custom_")` | bool | Determines pipeline below |
| 6a | (Built-in) Intent classify | `intent_classifier.classify_intent` | `(text, sector)` → `IntentResult` | Calls LLM `/completion` with JSON prompt, temperature 0.1 |
| 6b | (Built-in) RAG retrieve | `rag_retriever.retrieve` | `(text, sector)` → `RAGResult` | Top-3 chunks from `sector_<name>` ChromaDB collection |
| 6c | (Built-in) Build prompt | `prompt_builder.build_prompt` | persona + intent_instr + RAG + memory_hint → string | |
| 6d | (Custom) Lookup persona | `personas[sector]` | dict → string | `personas` is in-memory in `routers/persona.py` |
| 7 | History fetch | `memory_manager.get_history` | `session_id` → `list[{role, content}]` | Returns `[]` if Redis empty |
| 8 | Build messages | inline | `[system, *history, user]` | OpenAI-compatible chat shape |
| 9 | LLM call | `llm_client.chat_completion` | messages → `{text, tokens_used, latency_ms}` | POSTs to `/v1/chat/completions`. 120s timeout |
| 10 | Escalation check | `escalation.should_escalate` | `IntentResult` or `Exception` → bool | Critical intents OR low-confidence streaks OR LLM error |
| 11 | Output guardrails | `guardrails.check_output` | English reply → `(filtered, was_filtered)` | PII redaction + sector-specific phrase blocks |
| 12 | Translate output | `translator.from_english` | `(English reply, lang)` → user-language reply | Skipped if `lang == ENGLISH` |
| 13 | Store memory | `memory_manager.add_turn` | append English user+bot to Redis | Trims to 20 turns. Refreshes 24h TTL |
| 14 | Persist log | `db_session.save_conversation_log` | row → `conversation_logs` | Best-effort. Skipped if Postgres unreachable |
| 15 | Emit logs | `logger.info(extra={...})` | stdout + `logs/app.log` + `logs/app.json.log` | Includes input_original, input, output, output_translated |
| 16 | Return | `ChatResponse` | JSON to client | `reply` is the user-language version |

### Outputs (the response body)

```json
{
  "reply": "string (in lang)",
  "session_id": "string (UUID)",
  "intent": "string|null",
  "confidence": "float|null",
  "sources": "list of {doc_id, chunk_index, relevance}|null",
  "escalated": "bool"
}
```

### Early-exit paths

| Condition | Returns | Status |
|---|---|---|
| Input guardrail blocks | Translated apology message | 200 |
| Custom persona not found | HTTPException | 404 |
| LLM error + escalation | Translated escalation message | 200 |
| LLM error, no escalation | HTTPException | 503 |
| Critical intent | Translated escalation message | 200 |

---

## 3. Internal Call Graph

```
chat.py (orchestrator)
├── helpers.sanitize_input
├── helpers.generate_session_id
├── translator.to_english ────────► IndicTrans2 gateway /translate
├── guardrails.check_input
├── memory_manager.get_history ───► Redis GET session:<id>
├── intent_classifier.classify_intent
│     └── llm_client.generate ────► llama.cpp /completion
├── rag_retriever.retrieve ────────► ChromaDB query
├── routers/persona.personas (dict lookup)
├── prompt_builder.build_prompt
│     ├── prompts.base_system.get_system_prompt
│     └── (uses IntentResult, RAGResult, history)
├── llm_client.chat_completion ────► llama.cpp /v1/chat/completions
├── escalation.should_escalate
├── escalation.get_escalation_message
├── guardrails.check_output
├── translator.from_english ───────► IndicTrans2 gateway /translate
├── memory_manager.add_turn ───────► Redis SET session:<id> TTL=86400
├── db_session.save_conversation_log ► Postgres INSERT into conversation_logs
└── logger.info (with extra={...})
```

Every dotted-arrow represents an external network or DB call; everything else is in-process.

---

## 4. Module Deep-Dive

### 4.1 `app/main.py`

| Element | Behavior |
|---|---|
| `lifespan(app)` | startup: `memory_manager.connect()` → `init_db()`; shutdown: reverse |
| CORS | `allow_origins=["*"]`, `allow_credentials=True` (browser-incompatible combo, dev-only) |
| Routers mounted | `chat`, `agents`, `documents`, `analytics`, `tenants`, `persona` |
| `GET /` | 307 redirect to `/ui/test-ui.html` |
| `GET /health` | calls `llm_client.health_check()` (HEAD on llama.cpp `/health`); returns `HealthResponse` |
| Static mount | `/ui/*` → `frontend/` directory |

### 4.2 `app/config.py`

`Settings(BaseSettings)` reads from `.env` and env vars. Cached via `@lru_cache`.

| Field | Default | Source |
|---|---|---|
| `llama_server_url` | `http://localhost:8080` | `LLAMA_SERVER_URL` |
| `app_host` | `0.0.0.0` | `APP_HOST` |
| `app_port` | `8000` | `APP_PORT` |
| `debug` | `True` | `DEBUG` |
| `chroma_persist_dir` | `./data/chromadb` | `CHROMA_PERSIST_DIR` |
| `embedding_model` | `all-MiniLM-L6-v2` | `EMBEDDING_MODEL` |
| `translation_url` | `https://thousand-length-percentage-candle.trycloudflare.com` | `TRANSLATION_URL` |
| `redis_url` | `redis://localhost:6379/0` | `REDIS_URL` |
| `database_url` | `postgresql+asyncpg://postgres:password@localhost:5432/chatagent` | `DATABASE_URL` |
| `api_secret_key` | `change-this-secret` | `API_SECRET_KEY` |
| `rate_limit` | `60/minute` | `RATE_LIMIT` |
| `max_memory_turns` | `20` | `MAX_MEMORY_TURNS` |

### 4.3 `app/services/llm_client.py`

Singleton `llm_client = LLMClient()`. Two endpoints, both with structured logging.

#### `generate(prompt, system_prompt, max_tokens, temperature, stop) → dict`

- POST `{base_url}/completion`
- Payload: `{prompt: formatted, n_predict, temperature, stop, stream:false}`
- `_format_prompt()` wraps user/system in **Gemma 3** turn markers: `<start_of_turn>system\n…<end_of_turn>\n<start_of_turn>user\n…<end_of_turn>\n<start_of_turn>model\n`
- Returns `{text, tokens_used, latency_ms}`
- Logs `{endpoint, max_tokens, temperature, system_prompt_preview, prompt_preview, output, tokens_used, latency_ms}` on success
- Logs `{endpoint, latency_ms, error}` on failure (re-raises)

#### `chat_completion(messages, max_tokens, temperature) → dict`

- POST `{base_url}/v1/chat/completions` (OpenAI-compatible)
- Payload: `{messages, max_tokens, temperature}`
- Returns `{text, tokens_used, latency_ms}` from `choices[0].message.content` and `usage.total_tokens`
- Logs `{endpoint, messages_count, system_prompt_preview, user_message, output, tokens_used, latency_ms}`

#### `health_check() → bool`

- GET `{base_url}/health`, 5s timeout, `True` if 200.

### 4.4 `app/services/translator.py`

Singleton functions; thin wrapper over `httpx.AsyncClient`.

| Function | Behavior |
|---|---|
| `_translate(text, src, tgt)` | POST `{translation_url}/translate` `{text, src_lang, tgt_lang}`. 15s timeout. Returns `output` field, or original on any exception. Logs `{src_lang, tgt_lang, input, input_len, output, output_len, latency_ms}` on success and `{..., error}` on failure |
| `to_english(text, src_lang="auto")` | Short-circuits if `src == ENGLISH`. Else delegates to `_translate(text, src, "ENGLISH")` |
| `from_english(text, tgt_lang)` | Short-circuits if `tgt == ENGLISH`. Else `_translate(text, "ENGLISH", tgt)` |

Lang codes accepted: any IndicTrans2 key (`HINDI`) or FLORES-200 code (`hin_Deva`, `hin_Latn`). Append `_Latn` for Roman script output.

### 4.5 `app/services/intent_classifier.py`

#### `SECTOR_INTENTS` dict

Per-sector lists of `{intent, description}` dicts. Defaults to retail if sector unknown.

| Sector | Intent count |
|---|---|
| retail | 7 (order_tracking, refund_request, return_request, product_inquiry, payment_issue, complaint, general_query) |
| education | 7 (course_info, admission_process, fee_inquiry, exam_schedule, placement_query, campus_facilities, general_query) |
| medical | 8 (book_appointment, doctor_availability, report_collection, department_info, visiting_hours, health_package, emergency, general_query) |
| real_estate | 7 (property_search, site_visit, emi_calculation, document_checklist, locality_info, builder_info, general_query) |
| banking | 9 (account_inquiry, loan_eligibility, emi_calculation, credit_card, kyc_status, transaction_dispute, fd_rates, branch_locator, general_query) |
| tourism | 8 (itinerary_planning, hotel_recommendation, transport_info, visa_guidance, travel_package, local_attractions, budget_estimate, general_query) |

#### `classify_intent(message, sector) → IntentResult`

1. Format `CLASSIFICATION_PROMPT` with intent list and message.
2. Call `llm_client.generate(temperature=0.1, max_tokens=200)`.
3. Strip ` ```json ` fences, `json.loads`.
4. Clamp confidence to `[0.0, 1.0]`.
5. On parse failure: returns `IntentResult(intent="general_query", confidence=0.3)`.

LLM is asked to extract `params` too — entity values like `order_id`, `doctor_name`. Stored in `IntentResult.params`.

### 4.6 `app/services/rag_retriever.py`

Singleton `rag_retriever = RAGRetriever()`. Wraps a `chromadb.PersistentClient`.

| Method | Behavior |
|---|---|
| `_get_collection(sector)` | Lazily creates `sector_<name>` collection with cosine-distance HNSW |
| `add_document(sector, doc_id, content, metadata, chunk_size=500, chunk_overlap=50)` | Word-tokenize → chunks → `collection.add(documents, ids, metadatas)`. Chunk IDs: `{doc_id}_chunk_{i}`. Returns count |
| `retrieve(query, sector, top_k=3)` | `collection.query(query_texts=[query], n_results=top_k)`. Returns `RAGResult(chunks, sources, total_chunks)`. Source `relevance = 1 - cosine_distance` |
| `delete_document(sector, doc_id)` | `collection.get(where={doc_id})` → `collection.delete(ids)` |
| `_chunk_text(text, size, overlap)` | Plain word-split with stride `size - overlap` |

Embedding model: ChromaDB default (`all-MiniLM-L6-v2`, 384-dim). Set in config but not wired into Chroma — Chroma uses its own.

### 4.7 `app/services/prompt_builder.py`

#### `build_prompt(sector, intent, rag_context, memory) → str`

Concatenation order (separated by `\n\n`):

1. Base persona — `prompts.base_system.get_system_prompt(sector)`. ~25 lines per sector.
2. Intent instructions (only if intent != `general_query`) — `_get_intent_instruction(sector, intent)`.
3. Extracted params — `EXTRACTED INFO: order_id: 12345, ...` if `intent.params` non-empty.
4. RAG block — `RELEVANT INFORMATION FROM KNOWLEDGE BASE:\n<chunk1>\n---\n<chunk2>\n...` (max 3 chunks).
5. Memory hint — turn count, "refer to previous context".

#### `INTENT_INSTRUCTIONS` dict

Per-sector mapping of `intent → one-line instruction`. Not all intents have instructions (general_query has none, falls back to base persona).

### 4.8 `app/services/memory_manager.py`

Singleton `memory_manager`. Async Redis client.

| Method | Behavior |
|---|---|
| `connect()` | `redis.asyncio.from_url(redis_url, decode_responses=True)` |
| `disconnect()` | `redis.close()` |
| `get_history(session_id) → list[dict]` | `GET session:<id>` → `json.loads` (or `[]`) |
| `add_turn(session_id, user_msg, bot_reply, metadata=None)` | Read → append `{role:"user", content}` and `{role:"assistant", content}` → trim to `MAX_TURNS*2 = 40` items → `SET session:<id> json EX 86400` |
| `clear(session_id)` | `DEL session:<id>` |
| `get_session_metadata(session_id) → dict` | `{session_id, turns, ttl_seconds}` |

Stored data is **English-only** — translation happens at the chat-orchestrator layer, memory holds the canonical English form so multi-turn context is consistent.

### 4.9 `app/services/guardrails.py`

#### `check_input(message) → (blocked, reason)`

Iterates compiled regex lists:

- `INJECTION_PATTERNS` — 12 entries: `ignore (all )?previous instructions`, `ignore (all )?above`, `disregard (all )?previous`, `forget (everything|all|your) (instructions|rules|guidelines)`, `you are now`, `act as (if|though) you`, `pretend (you are|to be)`, `new instruction[s]?:`, `system prompt:`, `<system>`, `jailbreak`, `DAN mode`. → reason `prompt_injection`.
- `HARMFUL_PATTERNS` — 3 entries: bomb-making, hacking, fake document generation. → reason `harmful_content`.
- Length > 4000 → reason `message_too_long`.

All regex are case-insensitive. First match wins.

#### `check_output(response, sector) → (filtered, was_filtered)`

Two-pass:

1. **PII redaction** — for each `(name, regex)` in `PII_PATTERNS`:
   - `aadhaar`: `\b\d{4}\s?\d{4}\s?\d{4}\b`
   - `pan`: `\b[A-Z]{5}\d{4}[A-Z]\b`
   - `phone`: `\b(?:\+91[\-\s]?)?[6-9]\d{9}\b`
   - `email`: standard
   - `card_number`: `\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b`
   - `account_number`: `\b\d{9,18}\b` (over-broad — see Limitations)

   Match → replace with `[<NAME>_REDACTED]`. Sets `was_filtered = True`.

2. **Sector phrase block** — if any phrase in `SECTOR_BLOCKED_PHRASES[sector]` matches (case-insensitive substring regex), entire reply is replaced with a generic disclaimer.
   - `medical`: `you should take`, `i diagnose`, `i recommend taking`, `your diagnosis is`, `you have (a |the )?disease`
   - `banking`: `your password is`, `your otp is`, `your pin is`, `invest in`, `guaranteed returns`

### 4.10 `app/services/escalation.py`

| Function | Behavior |
|---|---|
| `should_escalate(intent=None, error=None, low_confidence_count=0)` | Escalates if: `error is not None` OR `intent.intent in ALWAYS_ESCALATE[sector]` OR `intent.confidence < 0.4 AND low_confidence_count >= 3` |
| `get_escalation_message(sector)` | Returns sector-specific copy from a small dict. Defaults to a generic "connecting human agent" |

`ALWAYS_ESCALATE`: `medical → [emergency]`, `banking → [transaction_dispute]`.

### 4.11 `app/services/queue_manager.py`

Defined but **not invoked** anywhere in the chat path. Has `asyncio.Semaphore(MAX_CONCURRENT=4)` for GPU throttling. Wire `acquire/release` around `llm_client.chat_completion` if you need concurrency limits.

### 4.12 `app/prompts/base_system.py`

`SECTOR_PROMPTS` — six long-form persona strings. Each has SCOPE / RULES / GUARDRAILS sections. `get_system_prompt(sector)` falls back to `retail` if unknown.

### 4.13 `app/models/db_session.py`

Async engine + `save_conversation_log(**fields)`. `init_db()` runs `Base.metadata.create_all()` (no Alembic). Module-level flag `_db_ready` short-circuits writes when Postgres is down.

### 4.14 `app/utils/logger.py`

Each `get_logger(name)` returns a logger with three handlers:

| Handler | Target | Format |
|---|---|---|
| `StreamHandler` | stdout | `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s` |
| `RotatingFileHandler` | `logs/app.log` | same text format. 10 MB × 5 backups |
| `RotatingFileHandler` | `logs/app.json.log` | `JsonFormatter` (one JSON object per line). 10 MB × 5 backups |

`JsonFormatter` strips standard `LogRecord` attrs; everything else passed via `extra={...}` becomes a top-level field.

### 4.15 Routers (HTTP-only, no logic)

| Router | Prefix | Endpoints |
|---|---|---|
| `chat` | `/api` | `POST /chat`, `DELETE /session/{id}` |
| `agents` | `/api/agents` | `GET /sectors`, `GET /{sector}`, `PUT /{sector}`, `GET /{sector}/intents` |
| `documents` | `/api/documents` | `POST /upload`, `POST /add-text`, `POST /search`, `DELETE /{sector}/{doc_id}` |
| `analytics` | `/api/analytics` | `GET /summary`, `GET /conversations`, `GET /intents` (all return mock data) |
| `tenants` | `/api/tenants` | `POST /`, `GET /`, `GET /{id}`, `PATCH /{id}/rate-limit`, `DELETE /{id}` |
| `persona` | `/api/persona` | `POST /create`, `GET /list`, `GET /{id}`, `DELETE /{id}` |

Persona creation calls `llm_client.generate` with `EXTRACT_PROMPT` (temp 0.1) to coerce a free-text persona into `{agent_name, company, description, services[], highlight_services[]}` JSON.

---

## 5. Data Shapes (All Schemas)

From [`app/models/schemas.py`](app/models/schemas.py):

### `ChatRequest`
```python
message: str       # min=1, max=4000
session_id: str | None
sector: str = "retail"
tenant_id: str | None
src_lang: str = "auto"
lang: str = "ENGLISH"
```

### `ChatResponse`
```python
reply: str
session_id: str
intent: str | None
confidence: float | None
sources: list | None      # [{doc_id, chunk_index, relevance}]
escalated: bool = False
```

### `IntentResult`
```python
intent: str
confidence: float    # [0.0, 1.0]
sector: str
params: dict        # extracted entities, e.g. {"order_id": "12345"}
```

### `HealthResponse`
```python
status: str          # "ok" | "degraded"
llm_status: str      # "connected" | "disconnected"
timestamp: datetime
```

### `RAGResult` (dataclass in `rag_retriever.py`)
```python
chunks: list[str]
sources: list[dict]        # [{doc_id, chunk_index, relevance}]
total_chunks: int
```

### `AgentConfig`, `DocumentUpload`, `SessionData`, `ConversationLog`, `AnalyticsSummary` — see schemas.py. Largely unused at runtime (the live chat path doesn't construct them).

---

## 6. Pattern Matching Internals

### 6.1 Intent matching

LLM-based, not regex. The classification prompt:
- Lists intents as `- {intent}: {description}`.
- Asks for strict JSON: `{"intent": "<name>", "confidence": <0..1>, "params": {}}`.
- Includes 2 few-shot examples (order tracking, appointment booking).

Confidence < 0.4 + 3 consecutive low-confidence turns → escalate. Currently the consecutive counter is **not tracked** in code (passed as 0 always) — escalation only fires on critical intents.

### 6.2 RAG matching

ChromaDB cosine similarity over default sentence-transformer embeddings. No reranker. `top_k=3`. Distance to relevance: `relevance = 1 - distance`. Empty collection → empty result.

### 6.3 Sector matching

`sector` field is a free `str`. Custom personas have `sector.startswith("custom_")`. Built-in lookup uses `SECTOR_PROMPTS.get(sector, SECTOR_PROMPTS["retail"])` — unknown sectors silently fall back to retail.

### 6.4 Language matching (translator)

Gateway accepts both IndicTrans2 keys (`HINDI`) and FLORES-200 codes (`hin_Deva`). Roman output: append `_Latn` to any Indic key.

| Internal short-circuits | Behavior |
|---|---|
| `to_english` if `src=="ENGLISH"` | skip API call |
| `from_english` if `tgt=="ENGLISH"` | skip API call |
| Empty/whitespace text | return as-is (no API call) |
| API error / timeout | log warning, return original text |

---

## 7. Logging Specification

### 7.1 Loggers and their fields

| Logger name | Source | Key `extra` fields |
|---|---|---|
| `chat` | routers/chat.py | `session_id, sector, tenant_id, src_lang, tgt_lang, input_original, input, output, output_translated, intent, confidence, latency_ms, tokens_used, rag_chunks` |
| `llm` | services/llm_client.py | `endpoint, messages_count, max_tokens, temperature, system_prompt_preview, user_message OR prompt_preview, output, tokens_used, latency_ms, error` |
| `translator` | services/translator.py | `src_lang, tgt_lang, input, input_len, output, output_len, latency_ms, error` |
| `intent` | services/intent_classifier.py | `sector, user_message, intent, confidence, params, raw_llm_output, error` |
| `rag` | services/rag_retriever.py | (text only — chunks added/found counts) |
| `memory` | services/memory_manager.py | (text only — connect/disconnect) |
| `guardrails` | services/guardrails.py | (text only — pattern name on match) |
| `escalation` | services/escalation.py | (text only — reason) |
| `db` | models/db_session.py | (text only — table ready / error) |
| `agents`, `documents`, `tenants`, `persona`, `analytics` | routers | (text only — admin events) |

### 7.2 Log destinations

Every `logger.info / .warning / .error` writes to all three:
1. **stdout** — text format
2. **`logs/app.log`** — text format, rotating 10 MB × 5
3. **`logs/app.json.log`** — JSON Lines, rotating 10 MB × 5

### 7.3 JsonFormatter output shape

```json
{
  "timestamp": "2026-04-27T16:02:11",
  "level": "INFO",
  "logger": "chat",
  "message": "[<session_id>] in=... | out=... | latency=...ms tokens=...",
  "<extra_key>": "<extra_value>",
  ...
}
```

### 7.4 Per-chat log fan-out (one user request)

```
1. translator   src=auto → tgt=ENGLISH    (input translation, if applicable)
2. chat         session_id sector lang msg preview
3. llm          /completion endpoint      (intent classifier call)
4. intent       sector intent confidence
5. rag          query found N chunks      (text only)
6. llm          /v1/chat/completions      (main reply call)
7. translator   src=ENGLISH → tgt=...     (output translation, if applicable)
8. chat         in/out summary, full structured payload
```

---

## 8. Database Schema

PostgreSQL tables defined in [`app/models/database.py`](app/models/database.py). Only `conversation_logs` is actively populated.

### `conversation_logs`

| Column | Type | Index | Nullable | Notes |
|---|---|---|---|---|
| `id` | int (auto PK) | PK | no | |
| `session_id` | varchar(64) | yes | no | |
| `tenant_id` | varchar(64) | yes | yes | |
| `sector` | varchar(32) | yes | no | |
| `user_message` | text | no | no | English version (post-translation) |
| `bot_reply` | text | no | no | English version (pre-translation) |
| `intent` | varchar(64) | no | yes | NULL for custom personas |
| `confidence` | float | no | yes | |
| `latency_ms` | float | no | no | end-to-end |
| `tokens_used` | int | no | default 0 | from llama.cpp `usage.total_tokens` |
| `rag_chunks` | int | no | default 0 | |
| `escalated` | bool | no | default false | (currently always false — escalation paths don't write log) |
| `created_at` | datetime | yes | server default `now()` | |

### `agent_configs` (defined, unused)

`tenant_id`, `sector`, `name`, `system_prompt`, `intents (JSON)`, `guardrail_rules (JSON)`, `is_active`, `created_at`, `updated_at`.

### `tenants` (defined, unused)

`tenant_id (unique)`, `name`, `api_key (unique)`, `sectors (JSON)`, `rate_limit (int)`, `is_active`, `created_at`.

### Schema management

- `init_db()` runs `Base.metadata.create_all` on startup. No Alembic.
- For production: install Alembic, `alembic init`, generate revision, switch `init_db` to a no-op or migration runner.

---

## 9. Configuration Variables

| Env var | Default | Used by |
|---|---|---|
| `LLAMA_SERVER_URL` | `http://localhost:8080` | `llm_client.py` |
| `APP_HOST` | `0.0.0.0` | `main.py` (uvicorn args) |
| `APP_PORT` | `8000` | `main.py` |
| `DEBUG` | `True` | `main.py` (uvicorn `reload`) |
| `CHROMA_PERSIST_DIR` | `./data/chromadb` | `rag_retriever.py` |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | declared but Chroma uses its own default |
| `TRANSLATION_URL` | trycloudflare URL | `translator.py` |
| `REDIS_URL` | `redis://localhost:6379/0` | `memory_manager.py`, `queue_manager.py` |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:password@localhost:5432/chatagent` | `db_session.py` |
| `API_SECRET_KEY` | `change-this-secret` | `middleware/auth.py` (not wired) |
| `RATE_LIMIT` | `60/minute` | `middleware/rate_limiter.py` (not wired) |
| `MAX_MEMORY_TURNS` | `20` | `memory_manager.py` |

---

## 10. Translation Pipeline Internals

### 10.1 Gateway contract

**Endpoint**: `POST {translation_url}/translate`

Request:
```json
{
  "text": "string (required, min 1)",
  "src_lang": "auto | <IndicTrans2 key> | <FLORES-200 code>",
  "tgt_lang": "<IndicTrans2 key> | <FLORES-200 code>"
}
```

Response: `{"output": "string"}`. 422 on validation error.

### 10.2 Wiring in chat pipeline

```
user_message_original ── to_english(src_lang) ──► user_message (English)
                                                     │
                                                     ▼
                                            [guardrails, intent, RAG, prompt, LLM]
                                                     │
                                                     ▼
                                            bot_reply (English)
                                                     │
                                                     ├── memory.add_turn (English)
                                                     ├── conversation_logs.bot_reply (English)
                                                     │
                                                     ▼
                                            from_english(tgt_lang) ──► bot_reply_translated ──► response
```

### 10.3 Why translation runs early/late

- **Input translated first** so guardrail regex (English-tuned) can catch attacks regardless of source language.
- **Memory stored in English** so multi-turn context stays consistent even if user switches `src_lang` mid-chat.
- **Output translated last** so guardrail regex (PII redaction, blocked phrases) operates on canonical English text.

### 10.4 Failure handling

Best-effort: on timeout, HTTP error, or JSON parse error, the original text is returned untranslated and a `WARNING` is logged. Chat continues — the LLM may receive non-English input and may respond non-English, but the request does not fail.

### 10.5 Supported language codes

See [REFERENCE_GUIDE.md §Languages](REFERENCE_GUIDE.md) for the full table. Quick reference:

- 22 native scripts (HINDI, BENGALI, TAMIL, TELUGU, ...)
- 10 Roman variants (HINDI_Latn, TELUGU_Latn, TAMIL_Latn, ...)
- ENGLISH (eng_Latn)

---

*Generated 2026-04-27. Pair with REFERENCE_GUIDE.md.*

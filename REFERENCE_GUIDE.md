# REFERENCE_GUIDE — Setup, Usage, and Everything Around the Code

Companion to [TECH_DOCS.md](TECH_DOCS.md). This doc covers running, using, troubleshooting, and extending the platform — anything that isn't the internal call-graph itself.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Project Layout](#2-project-layout)
3. [Frontend Usage](#3-frontend-usage)
4. [API Reference with Examples](#4-api-reference-with-examples)
5. [Language Support (Full Table)](#5-language-support-full-table)
6. [Extending the System](#6-extending-the-system)
7. [Deployment](#7-deployment)
8. [Troubleshooting](#8-troubleshooting)
9. [Security & Limitations](#9-security--limitations)
10. [Performance Notes](#10-performance-notes)
11. [Glossary](#11-glossary)
12. [FAQ](#12-faq)

---

## 1. Quick Start

### Prerequisites

| Component | Required | Notes |
|---|---|---|
| Python 3.11+ | Yes | |
| `llama.cpp` server on port 8080 | Yes | Loads Gemma 3 / Qwen GGUF |
| Redis | Yes (for memory) | Default `localhost:6379` |
| PostgreSQL | Optional | Without it, conversation logs only go to files |
| ChromaDB | Auto | File-based, created in `./data/chromadb` |
| Translation gateway | Optional | Without it, multi-language passthroughs unchanged |

### Setup

```bash
# 1. Clone, virtualenv, deps
git clone <repo> && cd Conversational_Agents
python -m venv Agent_env
source Agent_env/bin/activate
pip install -r requirements.txt

# 2. Config
cp .env.example .env

# 3. Start dependencies (in separate terminals)
./llama-server -m your-model.gguf -c 4096 --port 8080
redis-server &

# Optional: PostgreSQL via Docker
docker run -d --name chatagent-postgres \
  -e POSTGRES_DB=chatagent -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password -p 5432:5432 postgres:16-alpine

# 4. Run app (with hot reload in dev)
python -m app.main
```

### Smoke test

```bash
curl http://localhost:8000/health
# {"status":"ok","llm_status":"connected","timestamp":"..."}

curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello","sector":"retail"}'
```

Open [http://localhost:8000](http://localhost:8000) in a browser → redirects to the test UI.

---

## 2. Project Layout

```
Conversational_Agents/
├── app/                          # Backend Python code
│   ├── main.py                   # FastAPI entrypoint, lifespan, routes
│   ├── config.py                 # Settings loaded from .env
│   ├── routers/                  # HTTP endpoints
│   ├── services/                 # Business logic (LLM, RAG, translation, etc.)
│   ├── prompts/base_system.py    # 6 sector persona prompts
│   ├── models/                   # Pydantic + SQLAlchemy schemas, DB session
│   ├── middleware/               # Auth, rate-limit, logging (defined, not wired)
│   └── utils/                    # logger, helpers
├── frontend/
│   ├── test-ui.html              # Default UI — served at GET /
│   ├── dashboard/                # React 19 + Vite playground
│   └── widget/chat-widget.js     # Embeddable chat bubble
├── data/chromadb/                # Vector DB persistence (auto-created)
├── logs/                         # Log files (auto-created)
│   ├── app.log                   #   Human-readable text
│   └── app.json.log              #   JSON Lines, machine-parseable
├── tests/                        # pytest tests
├── requirements.txt
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── TECH_DOCS.md                  # Internal technical reference
└── REFERENCE_GUIDE.md            # This file
```

---

## 3. Frontend Usage

### 3.1 Test UI ([frontend/test-ui.html](frontend/test-ui.html))

The default-served UI. Features:

- **Sector tabs** — switch between Retail / Education / Medical / Real Estate / Banking / Tourism, plus a **+ Choose Persona** button to create a custom agent.
- **Landing screen** — service buttons (e.g., "Track Order", "Refund") that auto-fill the input.
- **Language dropdowns** above the input bar:
  - **Input** — defaults to "Auto-detect". Lets you tell the server what language you're typing.
  - **Output** — defaults to "English". Whatever you pick, the bot's reply is translated to it (including Roman-script options like Hinglish, Telugu Roman, etc.).
- **Sources** tag — when RAG returns docs, they're shown as `N sources` under each bot reply.
- **Intent + confidence** tags shown under each reply.
- **+ button** (top right) — clears the conversation (calls `DELETE /api/session/{id}`).
- **SOS button** (medical sector only) — sends an emergency message that triggers escalation.

### 3.2 React Playground ([frontend/dashboard/](frontend/dashboard/))

Vite + React 19 single-page app, [`ChatPlayground.jsx`](frontend/dashboard/ChatPlayground.jsx). Run with:

```bash
cd frontend/dashboard
npm install
npm run dev    # localhost:5173
```

Hardcodes `API_URL = http://localhost:8000`.

### 3.3 Embeddable Widget ([frontend/widget/chat-widget.js](frontend/widget/chat-widget.js))

Drop this into any website:

```html
<script
    src="http://localhost:8000/ui/widget/chat-widget.js"
    data-api="http://localhost:8000"
    data-sector="retail"
    data-key="sk-your-api-key"
    data-title="ShopEasy Support">
</script>
```

Renders a floating chat bubble in the bottom-right corner.

---

## 4. API Reference with Examples

All endpoints return JSON. Most accept JSON bodies.

### Chat

#### `POST /api/chat`

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Where is my order #12345?",
    "session_id": null,
    "sector": "retail",
    "src_lang": "auto",
    "lang": "ENGLISH"
  }'
```

Response:
```json
{
  "reply": "Let me look up #12345... it's out for delivery, arriving by 5 PM today.",
  "session_id": "abc-123-def-456",
  "intent": "order_tracking",
  "confidence": 0.95,
  "sources": [],
  "escalated": false
}
```

Multi-turn — pass back the `session_id`:
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the courier?","session_id":"abc-123-def-456","sector":"retail"}'
```

Multilingual — Hindi → Hinglish reply:
```bash
curl -X POST http://localhost:8000/api/chat \
  -d '{"message":"मेरा ऑर्डर कहाँ है","sector":"retail","src_lang":"HINDI","lang":"HINDI_Latn"}'
```

#### `DELETE /api/session/{session_id}`

```bash
curl -X DELETE http://localhost:8000/api/session/abc-123-def-456
# {"status":"cleared","session_id":"abc-123-def-456"}
```

### Agents

```bash
curl http://localhost:8000/api/agents/sectors
# {"sectors":["retail","education","medical",...],"total":6}

curl http://localhost:8000/api/agents/retail
# Full agent config (persona + intents)

curl http://localhost:8000/api/agents/retail/intents
# Available intents for the sector
```

### Documents (RAG knowledge base)

```bash
# Upload a .txt/.md/.csv file
curl -X POST http://localhost:8000/api/documents/upload \
  -F "sector=retail" \
  -F "file=@product_catalog.txt"

# Add raw text
curl -X POST 'http://localhost:8000/api/documents/add-text?sector=retail&title=FAQ&content=Returns%20accepted%20within%2015%20days...'

# Search (test retrieval)
curl -X POST 'http://localhost:8000/api/documents/search?sector=retail&query=warranty&top_k=3'

# Delete
curl -X DELETE http://localhost:8000/api/documents/retail/retail_abc12345
```

### Custom Personas

```bash
curl -X POST http://localhost:8000/api/persona/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "QuickKart Support",
    "prompt": "You are Roopa, a customer support agent at QuickKart..."
  }'
# {"persona_id":"custom_abc12345","name":"QuickKart Support",...}
```

Then use it as a sector:
```bash
curl -X POST http://localhost:8000/api/chat \
  -d '{"message":"hello","sector":"custom_abc12345"}'
```

### Tenants

```bash
# Create a tenant
curl -X POST 'http://localhost:8000/api/tenants/?name=ShopEasy&sectors=retail'
# {"tenant_id":"abc12345","api_key":"sk-...","message":"Save your API key — it won't be shown again."}

# List
curl http://localhost:8000/api/tenants/

# Update rate limit
curl -X PATCH 'http://localhost:8000/api/tenants/abc12345/rate-limit?rate_limit=600'
```

### Analytics (mock today)

```bash
curl 'http://localhost:8000/api/analytics/summary?days=7'
# Returns hardcoded zeros until you wire the Postgres queries.
```

### Auto-generated docs

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 5. Language Support (Full Table)

The translation gateway accepts both **IndicTrans2 keys** (`HINDI`) and **FLORES-200 codes** (`hin_Deva`). Use whichever you prefer; the UI dropdown sends keys.

### 5.1 Native scripts

| Key | FLORES-200 | Language |
|---|---|---|
| `ENGLISH` | `eng_Latn` | English |
| `HINDI` | `hin_Deva` | Hindi |
| `BENGALI` | `ben_Beng` | Bengali |
| `TAMIL` | `tam_Taml` | Tamil |
| `TELUGU` | `tel_Telu` | Telugu |
| `KANNADA` | `kan_Knda` | Kannada |
| `MALAYALAM` | `mal_Mlym` | Malayalam |
| `MARATHI` | `mar_Deva` | Marathi |
| `GUJARATI` | `guj_Gujr` | Gujarati |
| `PUNJABI` | `pan_Guru` | Punjabi |
| `ODIA` | `ory_Orya` | Odia |
| `ASSAMESE` | `asm_Beng` | Assamese |
| `URDU` | `urd_Arab` | Urdu |
| `NEPALI` | `npi_Deva` | Nepali |
| `KASHMIRI` | `kas_Arab` | Kashmiri |
| `SINDHI` | `snd_Arab` | Sindhi |
| `KONKANI` | `gom_Deva` | Konkani |
| `MAITHILI` | `mai_Deva` | Maithili |
| `MANIPURI` | `mni_Mtei` | Manipuri |
| `BODO` | `brx_Deva` | Bodo |
| `DOGRI` | `doi_Deva` | Dogri |
| `SANTALI` | `sat_Olck` | Santali |

### 5.2 Roman script (Latn) variants

Useful when you want output rendered in Latin letters (Hinglish-style).

| Key | FLORES-200 | Example |
|---|---|---|
| `HINDI_Latn` | `hin_Latn` | "Aapka order kahan hai?" |
| `BENGALI_Latn` | `ben_Latn` | |
| `TAMIL_Latn` | `tam_Latn` | |
| `TELUGU_Latn` | `tel_Latn` | "Mee order ekkada undi?" |
| `KANNADA_Latn` | `kan_Latn` | |
| `MALAYALAM_Latn` | `mal_Latn` | |
| `MARATHI_Latn` | `mar_Latn` | |
| `GUJARATI_Latn` | `guj_Latn` | |
| `PUNJABI_Latn` | `pan_Latn` | |
| `ODIA_Latn` | `ory_Latn` | |

### 5.3 Special source `auto`

Pass `src_lang: "auto"` and the gateway runs language ID (LID) before translation. The UI defaults to this.

### 5.4 Behavior matrix

| `src_lang` | `lang` | What runs |
|---|---|---|
| `ENGLISH` | `ENGLISH` | No translation calls. Zero overhead. |
| `auto` | `ENGLISH` | Input auto-detected → English. No output translation. |
| `auto` | `HINDI` | Input → English → LLM → Hindi |
| `HINDI` | `HINDI_Latn` | Hindi → English → LLM → Hinglish |
| `TELUGU_Latn` | `TELUGU` | Telugu Roman → English → LLM → Telugu |

---

## 6. Extending the System

### 6.1 Add a new intent to an existing sector

1. [`app/services/intent_classifier.py`](app/services/intent_classifier.py) — append to the right list in `SECTOR_INTENTS`:
   ```python
   {"intent": "loyalty_query", "description": "User asks about loyalty rewards"}
   ```
2. [`app/services/prompt_builder.py`](app/services/prompt_builder.py) — add to `INTENT_INSTRUCTIONS["retail"]`:
   ```python
   "loyalty_query": "Explain the rewards program and how to redeem points."
   ```

### 6.2 Add a brand-new sector

1. [`app/prompts/base_system.py`](app/prompts/base_system.py) — add a persona to `SECTOR_PROMPTS`.
2. [`app/services/intent_classifier.py`](app/services/intent_classifier.py) — add intents to `SECTOR_INTENTS`.
3. [`app/services/prompt_builder.py`](app/services/prompt_builder.py) — optionally add `INTENT_INSTRUCTIONS` entries.
4. [`app/services/escalation.py`](app/services/escalation.py) — optionally add critical intents to `ALWAYS_ESCALATE`.
5. [`frontend/test-ui.html`](frontend/test-ui.html) — add to `BUILT_IN` array (sector card).

### 6.3 Switch to a different LLM family

1. Stop llama.cpp; restart with the new model.
2. Edit `_format_prompt()` in [`llm_client.py`](app/services/llm_client.py) to match the model's chat template:
   - Llama 3: `<|start_header_id|>system<|end_header_id|>...<|eot_id|>`
   - Qwen: `<|im_start|>system\n...<|im_end|>`
   - ChatML / Mistral: see model card

### 6.4 Add a new language

1. Confirm the gateway supports it (see [INDICTRANS_LANG_MAP](#5-language-support-full-table)).
2. Add an `{v: "<KEY>", t: "<Display Name>"}` entry to `SRC_LANG_OPTS` in [`test-ui.html`](frontend/test-ui.html).

### 6.5 Add a new RAG document

```bash
curl -X POST http://localhost:8000/api/documents/upload \
  -F "sector=banking" \
  -F "file=@interest_rates.txt"
```

The text is chunked (500 words, 50 overlap) and stored in `sector_banking` ChromaDB collection.

### 6.6 Tighten input safety

Edit [`guardrails.py`](app/services/guardrails.py):
- Add patterns to `INJECTION_PATTERNS` or `HARMFUL_PATTERNS`
- Add PII regex to `PII_PATTERNS`
- Add per-sector blocked phrases to `SECTOR_BLOCKED_PHRASES`

### 6.7 Make analytics return real data

Wire [`routers/analytics.py`](app/routers/analytics.py) to query Postgres instead of returning zeros. The data is already in `conversation_logs`. Example:

```python
from sqlalchemy import select, func
from app.models.db_session import SessionLocal
from app.models.database import ConversationLogDB

async with SessionLocal() as s:
    q = select(func.count(), func.avg(ConversationLogDB.latency_ms)) \
        .where(ConversationLogDB.created_at > since)
    total, avg = (await s.execute(q)).first()
```

### 6.8 Turn on auth & rate limiting

In [`main.py`](app/main.py) add:
```python
from app.middleware.auth import AuthMiddleware
from app.middleware.rate_limiter import RateLimitMiddleware
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
```

Auth requires `X-API-Key` header matching `API_SECRET_KEY` in `.env` (or, after wiring, against the tenants table).

### 6.9 Persist tenants & personas across restarts

Currently in-memory dicts. Replace with `TenantDB` (from `database.py`) by:
- Adding session usage in [`routers/tenants.py`](app/routers/tenants.py)
- Adding a similar table for personas in [`database.py`](app/models/database.py)

---

## 7. Deployment

### 7.1 Single-server Docker

```bash
docker build -t chatagent .
docker run -d -p 8000:8000 \
  -e LLAMA_SERVER_URL=http://host.docker.internal:8080 \
  -e REDIS_URL=redis://redis:6379/0 \
  -e DATABASE_URL=postgresql+asyncpg://postgres:password@postgres:5432/chatagent \
  --name chatagent chatagent
```

### 7.2 Full stack via Compose

```bash
docker compose up -d
# Brings up: app, redis, postgres, prometheus, grafana
```

`docker-compose.yml` services:

| Service | Port | Volume |
|---|---|---|
| `app` | 8000 | `./data` |
| `redis` | 6379 | `redis_data` |
| `postgres` | 5432 | `postgres_data` |
| `prometheus` | 9090 | reads `./monitoring/prometheus.yml` |
| `grafana` | 3001 → 3000 | `grafana_data` |

### 7.3 Production checklist

- [ ] Tighten CORS in `main.py` (set explicit origins, not `*`)
- [ ] Wire auth + rate-limit middleware
- [ ] Move tenants and personas to PostgreSQL
- [ ] Replace `Base.metadata.create_all` with Alembic migrations
- [ ] Set `DEBUG=false` and `--workers > 1`
- [ ] Strong `API_SECRET_KEY`
- [ ] Use `redis-py` connection pooling settings appropriate for your worker count
- [ ] Log shipping to Loki / ELK / Datadog (consume `logs/app.json.log`)
- [ ] Replace the trycloudflare translation URL with a stable production endpoint

---

## 8. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `/health` returns `degraded` | llama.cpp not running or wrong port | Start `./llama-server -m model.gguf --port 8080` |
| `503 LLM service unavailable` on chat | llama.cpp connection failed | Same as above; check `LLAMA_SERVER_URL` in `.env` |
| `PostgreSQL unavailable` warning at startup | Postgres not running / wrong creds | Run docker postgres or fix `DATABASE_URL` |
| `Connection refused` on Redis | Redis not running | `redis-server` or `docker run -p 6379:6379 redis:7-alpine` |
| Translation fails silently | Cloudflare tunnel down | App keeps working with original text. Update `TRANSLATION_URL` |
| RAG returns no chunks | Sector collection empty | Upload docs via `POST /api/documents/upload` |
| Logs show only stdout, no files | `logs/` not writable | `mkdir logs && chmod 755 logs` |
| Test `test_root` fails | Test expects old `GET /` JSON, but `/` now redirects | Skip or update the test |
| 422 on `/api/chat` | Missing/invalid `message` field, or message > 4000 chars | Check request body |
| Chat works but reply not translated | Gateway returned 200 but with empty `output` | Check `logs/app.json.log` filter `logger=="translator"` |
| 4 uvicorn workers see different tenants/personas | In-memory dicts not shared | Move to Postgres (see §6.9) |

### Debugging commands

```bash
# Watch live logs
tail -f logs/app.log

# Filter JSON logs by logger
tail -f logs/app.json.log | jq 'select(.logger=="translator")'

# Check Redis sessions
redis-cli KEYS 'session:*'
redis-cli GET session:<id>

# Check ChromaDB
ls -la data/chromadb/

# Check Postgres logs
docker exec -it chatagent-postgres psql -U postgres -d chatagent \
  -c "SELECT id,sector,latency_ms FROM conversation_logs ORDER BY id DESC LIMIT 5;"

# Tail llama.cpp from its own terminal
```

---

## 9. Security & Limitations

### Critical (fix before public exposure)

- **CORS open to `*` with credentials** in [main.py](app/main.py). Browsers reject the combo and it's wrong for production.
- **No authentication** on the chat endpoint. Anyone reachable can chat (and consume LLM tokens).
- **No rate limiting** wired in.
- **Translation gateway is a Cloudflare tunnel URL** — not stable. Will rotate.

### Functional gaps

- **`account_number` PII regex too broad** — `\b\d{9,18}\b` matches order IDs and other long numbers.
- **`ChatRequest.sector` is free `str`** — Pydantic accepts typos. Consider `Literal["retail",...]`.
- **Tenants & custom personas are in-memory.** Lost on restart, not multi-worker safe.
- **Analytics endpoints return mock zeros.** Real DB queries not implemented.
- **Early-exit chat paths don't write conversation logs** (LLM error, escalation) — only successful turns persist.
- **Queue manager defined but unused.** Concurrent chats hit llama.cpp without throttling.
- **Memory always English.** If translation fails, the LLM gets non-English text but memory then holds non-English content too.
- **Test `test_chat.py::test_root` is broken** — expects JSON at `/` but `/` now redirects to UI.

### Operational

- The asyncpg `DATABASE_URL` requires the `chatagent` database to **already exist** (Docker image creates it via `POSTGRES_DB`; if installing native, `createdb chatagent`).
- ChromaDB persists to `./data/chromadb`. Don't delete unless you want to lose all uploaded knowledge.

---

## 10. Performance Notes

| Step | Typical latency | Notes |
|---|---|---|
| Translation (input) | 200–800 ms | Skipped if `src_lang=ENGLISH` |
| Intent classification | 300–1500 ms | One small LLM call |
| RAG retrieval | 50–200 ms | ChromaDB local |
| Main LLM call | 1000–8000 ms | Dominates total latency. Depends on model size, GPU |
| Translation (output) | 200–800 ms | Skipped if `lang=ENGLISH` |
| Memory + DB persist | < 50 ms | Async, off the critical path post-response |

**Total**: typically 2–10s per turn for a 7B-class model on consumer GPU.

### Optimization knobs

- **Drop intent classification** for trusted sectors → save 1 LLM round-trip.
- **Lower `max_tokens`** in `chat_completion` if replies are too long.
- **Smaller chunk size + fewer chunks** in RAG → smaller prompts → faster.
- **`temperature=0`** for deterministic, faster generation when creativity isn't needed.
- **Wire `queue_manager`** if multiple users hammer the same GPU.

---

## 11. Glossary

- **Sector** — Industry vertical with a built-in persona (retail, medical, etc.).
- **Tenant** — A customer using your platform; multi-tenant means one server, many isolated customers.
- **Session** — One conversation, identified by UUID `session_id`. Holds short-term memory in Redis.
- **Intent** — Categorical label for what the user wants (e.g., `order_tracking`).
- **RAG** — Retrieval-Augmented Generation. Fetch relevant docs, stuff into the prompt.
- **Embedding** — Vector representation of text for similarity search.
- **Guardrails** — Filters that block bad input or sanitize bad output.
- **Escalation** — Hand off to a human agent when bot can't / shouldn't help.
- **System prompt** — The instructions defining persona, scope, and rules.
- **Chat template** — Model-specific token format for messages (Gemma `<start_of_turn>`, Llama `<|begin_of_text|>`, etc.).
- **TTL** — Time To Live; auto-deletion after N seconds (24h for sessions).
- **PII** — Personally Identifiable Information — phone, account numbers, emails. Redacted from outputs.
- **FLORES-200** — Standard 200-language code set (`hin_Deva`, `eng_Latn`, etc.).
- **IndicTrans2** — IndicLP's translation model. Our gateway wraps it.
- **LID** — Language ID, automatic detection of source language.

---

## 12. FAQ

**Q: Do I need PostgreSQL just to chat?**
No. The app starts with a warning if Postgres is down and skips DB log persistence. Chat still works; logs still go to files.

**Q: Do I need the translation gateway?**
Only for non-English chat. If it's down or unset, `to_english` / `from_english` return text unchanged and chat continues. English users have zero translation overhead.

**Q: Can two browser tabs share the same conversation?**
Only if they share the same `session_id`. Each fresh chat gets its own UUID. The frontend doesn't persist `session_id` across page reloads.

**Q: How long is conversation memory kept?**
24 hours (Redis TTL). Bumped to 24h on every new turn. Capped at 20 turns of history.

**Q: How do I disable a sector?**
Remove its entry from `SECTOR_PROMPTS` in [base_system.py](app/prompts/base_system.py). Also remove from `SECTOR_INTENTS` and the frontend's `BUILT_IN` array.

**Q: Can I run multiple sectors per chat?**
No — each request specifies one `sector`. To switch, start a new session.

**Q: What if a user types in multiple languages mid-chat?**
With `src_lang=auto`, each message is independently detected. Memory is stored in English so context survives switches. Output is translated to whatever `lang` was sent on each request.

**Q: What model should I use with llama.cpp?**
- **Gemma 3** (default chat template) — `_format_prompt` in `llm_client.py` is wired for it.
- **Qwen 2.5 / 3** — change template to `<|im_start|>...<|im_end|>`.
- **Any OpenAI-compatible server** — `chat_completion` will work without template changes.

7B+ params recommended for reasonable quality. 3B works for English-only, struggles on intent JSON.

**Q: Where do I look first when something breaks?**
1. `tail -f logs/app.log` — see live errors
2. `tail logs/app.json.log | jq` — structured per-call data
3. `/health` endpoint — confirms LLM connectivity
4. Redis CLI — `KEYS 'session:*'` confirms memory is being written

**Q: Can I use this with Anthropic / OpenAI APIs instead of llama.cpp?**
Yes — replace the body of `llm_client.chat_completion` with a call to the OpenAI / Anthropic SDK. The rest of the pipeline doesn't care.

**Q: How do I clear all sessions?**
```bash
redis-cli --scan --pattern 'session:*' | xargs redis-cli DEL
```

**Q: How do I reset the knowledge base for a sector?**
```bash
rm -rf data/chromadb/
# or programmatically:
curl -X DELETE http://localhost:8000/api/documents/retail/<doc_id>
```

---

*Pair with [TECH_DOCS.md](TECH_DOCS.md) for internals. Last updated 2026-04-27.*

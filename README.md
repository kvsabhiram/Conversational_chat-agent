# Chat Agent Platform

Multi-sector AI chat agents powered by a local LLM (Gemma 3 / Qwen) via llama.cpp.  
Supports 6 sectors: Education, Retail, Medical, Real Estate, Banking, Tourism.

## Architecture

```
User → Chat Widget → FastAPI → [Input Guardrails] → [Intent Classification]
     → [RAG Retrieval] → [Build Prompt] → LLM (llama.cpp) → [Output Guardrails]
     → Response → [Update Memory + Logs] → [Analytics]
```

## Multi-language Support

Conversations aren't limited to English — the agent can reply in roughly 100 languages, in the script the requested language calls for (native script by default, or transliterated/Roman script for the options explicitly offered that way, e.g. "Hindi (Roman script / Hinglish)").

- **No translation microservice in the loop.** The chat pipeline used to round-trip through a separate translation step; that's gone from `chat_graph.py`. Instead, Gemma is prompted to read the user's message and write its reply directly in the requested language — it's fluent enough across languages that this beats translate-in/translate-out (simpler, one less moving part, no double-translation quality loss).
- **Requesting a language:** `ChatRequest.lang` takes any plain language name — `"Hindi"`, `"Tamil"`, `"French"`, `"Hindi (Roman script / Hinglish)"`, etc. — there's no fixed enum or lookup table; whatever string is sent is interpolated straight into the LLM's system prompt. Defaults to `"ENGLISH"`. `ChatRequest.src_lang` is an optional hint about the incoming message's language/script (default `"auto"`) — it doesn't trigger any translation call, just nudges the LLM.
- **Known trade-off:** RAG retrieval and the sector-specific blocked-phrase guardrail (e.g. catching phrases like "you should take" / "i diagnose") are still English-pattern/embedding-centric and weren't extended for multilingual use, so retrieval quality and that one safety check may be weaker in non-English conversations. This is an accepted trade-off, not a bug. PII guardrails (Aadhaar/PAN/phone/email/card) are regex-based and language-agnostic, so they're unaffected.

## Quick Start

### Prerequisites
- Python 3.11+
- llama.cpp server running on port 8080 with your model loaded
- Redis (Phase 3+)
- PostgreSQL (Phase 3+)

### Phase 1: Core Engine

```bash
# 1. Clone and setup
cd chat-agent-platform
cp .env.example .env
pip install -r requirements.txt

# 2. Make sure llama.cpp is running
# ./llama-server -m your-model.gguf -c 4096 --port 8080

# 3. Start the API server
python -m app.main

# 4. Test it
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is my order #12345?", "sector": "retail"}'
```

### Phase 2: Intelligence Layer
Uncomment Phase 2 imports in `app/main.py` and `app/routers/chat.py`.

```bash
# Upload documents to knowledge base
curl -X POST http://localhost:8000/api/documents/upload \
  -F "sector=retail" \
  -F "file=@product_catalog.txt"

# Test RAG retrieval
curl -X POST http://localhost:8000/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{"sector": "retail", "query": "Samsung warranty policy"}'
```

### Phase 3: Safety + Scale
```bash
# Start Redis and PostgreSQL
docker-compose up redis postgres -d

# Uncomment Phase 3 imports in app/main.py
# Run database migrations
alembic upgrade head
```

### Phase 4: Production
```bash
# Full stack with monitoring
docker-compose up -d

# Create a tenant
curl -X POST http://localhost:8000/api/tenants/ \
  -H "Content-Type: application/json" \
  -d '{"name": "ShopEasy", "sectors": ["retail"]}'
```

## Embed Chat Widget

Add this to any website:
```html
<script
    src="https://your-domain.com/widget/chat-widget.js"
    data-api="https://your-domain.com"
    data-sector="retail"
    data-key="sk-your-api-key"
    data-title="ShopEasy Support">
</script>
```

## API Endpoints

| Method | Endpoint | Phase | Description |
|--------|----------|-------|-------------|
| POST | /api/chat | 1 | Send a chat message |
| GET | /health | 1 | Health check |
| GET | /api/agents/sectors | 2 | List sectors |
| GET | /api/agents/{sector} | 2 | Get agent config |
| POST | /api/documents/upload | 2 | Upload RAG document |
| POST | /api/documents/search | 2 | Test RAG search |
| GET | /api/analytics/summary | 4 | Analytics dashboard |
| POST | /api/tenants/ | 4 | Create tenant |

## Tech Stack

- **FastAPI** — API server
- **llama.cpp** — Local LLM inference
- **ChromaDB** — Vector store for RAG
- **Redis** — Session memory + request queue
- **PostgreSQL** — Conversation logs + configs
- **Prometheus + Grafana** — Monitoring (Phase 4)

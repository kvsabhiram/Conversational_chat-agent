# Chat Agent Platform — Integration Guide

Everything a client needs to embed or call the chat agents. You only need
**one endpoint** (`POST /api/chat`) for a working chatbot; the rest is optional.

---

## 1. Base URL

| Environment | Base URL |
|-------------|----------|
| Local dev   | `http://localhost:5000` |
| Production  | `https://<your-deployed-domain>` |

> The service listens on **port 5000** (not 8000 — older docs/examples say 8000, ignore them).

All responses are JSON. All request bodies are JSON unless noted (file upload uses multipart form).

## 2. Authentication

**Currently none is enforced** — no header or key is required to call the API.
The embeddable widget can send an `X-API-Key` header, but the backend does not
yet validate it, so you can omit it. (Auth is planned — see "Notes for later" below.)

CORS is fully open, so browser-based calls from any origin work today.

---

## 3. Primary endpoint — Chat

### `POST /api/chat`

Send one user message, get one bot reply. This is the only call needed for a
working chatbot.

**Request body**

| Field        | Type    | Required | Default    | Notes |
|--------------|---------|----------|------------|-------|
| `message`    | string  | ✅ yes   | —          | User's message. 1–4000 chars. |
| `session_id` | string  | no       | auto       | Omit on the **first** message; use the value returned to keep the conversation going. |
| `sector`     | string  | no       | `retail`   | Which agent to use (see §4), or a `custom_...` persona id (see §6). |
| `tenant_id`  | string  | no       | null       | Optional client identifier (for your own analytics/logging). |
| `src_lang`   | string  | no       | `auto`     | Language of the **incoming** message. `ENGLISH` skips translation. |
| `lang`       | string  | no       | `ENGLISH`  | Language the **reply** should be returned in. |

**Response body**

| Field        | Type            | Notes |
|--------------|-----------------|-------|
| `reply`      | string          | The bot's answer (already translated to `lang`). Show this to the user. |
| `session_id` | string          | **Store this** and send it back on the next message. |
| `intent`     | string \| null  | Detected intent (built-in sectors only). |
| `confidence` | number \| null  | 0.0–1.0 confidence of the intent. |
| `sources`    | array \| null   | Knowledge-base citations, if any were used. |
| `escalated`  | boolean         | `true` = the bot handed off to a human / hit an error. Route to a live agent. |

**cURL**

```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is my order?", "sector": "retail"}'
```

**JavaScript (browser / Node)**

```js
let sessionId = null; // persist across messages in this conversation

async function sendMessage(text) {
  const res = await fetch("http://localhost:5000/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: text,
      session_id: sessionId,   // null on first turn
      sector: "retail",
    }),
  });
  const data = await res.json();
  sessionId = data.session_id; // reuse on the next turn
  return data.reply;
}
```

**Python**

```python
import requests

BASE = "http://localhost:5000"
session_id = None

def send(text, sector="retail"):
    global session_id
    r = requests.post(f"{BASE}/api/chat", json={
        "message": text,
        "session_id": session_id,
        "sector": sector,
    })
    data = r.json()
    session_id = data["session_id"]
    return data["reply"]
```

### Session handling
- **First message:** omit `session_id`. The response gives you one.
- **Every message after:** send the same `session_id` back so the bot remembers context.
- Conversation history is kept server-side (last ~20 turns).

### `DELETE /api/session/{session_id}`
Clears a conversation's memory (e.g. "New chat" button).

```bash
curl -X DELETE http://localhost:5000/api/session/<session_id>
```

---

## 4. Available sectors (built-in agents)

Pass one of these as `sector`:

| `sector`      | Agent  | Use case |
|---------------|--------|----------|
| `retail`      | Priya  | E-commerce support: orders, returns, refunds, delivery |
| `education`   | Arjun  | Courses, admissions, fees, exams, scholarships |
| `medical`     | Dr. Meera | Appointments, doctor availability, reports (no diagnosis) |
| `real_estate` | Vikram | Listings, site visits, EMI estimates, locality info |
| `banking`     | Ananya | Accounts, loans, cards, EMI, KYC (no transactions) |
| `tourism`     | Riya   | Itineraries, hotels, transport, visa guidance |

Get this list programmatically: `GET /api/agents/sectors`.

---

## 5. Multi-language support

The pipeline runs in English internally and translates in/out automatically.

- `src_lang`: language you're sending in (e.g. `HINDI`, `TAMIL`, or `auto`). Use `ENGLISH` to skip.
- `lang`: language you want the reply in.

```json
{ "message": "मेरा ऑर्डर कहाँ है?", "src_lang": "HINDI", "lang": "HINDI", "sector": "retail" }
```

Translation is best-effort: if the translation service is down, the original text
is returned rather than erroring.

---

## 6. Custom agents (personas) — optional

Instead of a built-in sector, you can define your own agent from a prompt.

1. **Create it:**

   ```bash
   curl -X POST http://localhost:5000/api/persona/create \
     -H "Content-Type: application/json" \
     -d '{"prompt": "You are Sam, a support agent for Acme SaaS...", "name": "Acme Bot"}'
   ```
   Returns a `persona_id` like `custom_ab12cd34`.

2. **Chat with it** by passing that id as the `sector`:

   ```json
   { "message": "Hi", "sector": "custom_ab12cd34" }
   ```

Other persona routes: `GET /api/persona/list`, `GET /api/persona/{id}`, `DELETE /api/persona/{id}`.

---

## 7. Easiest path — drop-in widget

For a website that just wants a chat bubble, no code beyond one script tag:

```html
<script src="https://<your-domain>/ui/widget/chat-widget.js"
        data-api="https://<your-domain>"
        data-sector="retail"
        data-title="ShopEasy Support">
</script>
```

It renders a floating chat bubble, manages `session_id` for you, and calls
`/api/chat` under the hood. Set `data-api` to your base URL and `data-sector`
to any sector or `custom_...` id.

---

## 8. Health check

`GET /health` → `{"status": "ok", "llm_status": "connected", ...}`.
Use for uptime monitoring. `status` is `degraded` if the LLM backend is unreachable.

---

## 9. Errors

| Code | Meaning | What to do |
|------|---------|------------|
| `422` | Invalid body (e.g. empty `message`, >4000 chars) | Fix the request. |
| `404` | Unknown persona/tenant/sector | Check the id. |
| `503` | LLM backend unavailable | Retry with backoff; show a fallback message. |

On any failure, show a graceful "please try again" message — don't surface raw errors to end users.

---

## Notes for later (current limitations to be aware of)

These don't block integration but the integrator should know:

- **No auth yet.** Anyone with the URL can call it. Don't expose the raw API on
  the public internet for production without adding a key check / gateway.
- **Some state is in-memory.** Custom personas and tenants are stored in process
  memory. With the default 4-worker deployment they are **not shared across
  workers** and are lost on restart. For reliable custom personas in production,
  run a single worker or wait for the DB-backed version.
- **Analytics endpoints return mock data** until PostgreSQL is wired up.
- **Only `.txt`, `.md`, `.csv`** document uploads are supported (no PDF yet).

"""OpenAI-compatible adapter.

Lets external agent platforms (e.g. Chat Bucket's "Conversational chat agent")
use this backend as a **Custom LLM**. It exposes the two routes such platforms
expect — `GET /v1/models` and `POST /v1/chat/completions` — in OpenAI format,
and routes every turn through the existing /api/chat pipeline (persona, intent,
RAG, guardrails, translation, logging).

Mapping from the OpenAI request:
- `model`  -> the sector (`retail`, `banking`, ...) or a `custom_<id>` persona.
- `user`   -> the session id, so conversation memory persists across turns.
- last message with role "user" -> the message sent into the pipeline.
"""

import json
import time
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest
from app.routers.chat import chat as chat_pipeline
from app.prompts.base_system import get_all_sectors
from app.utils.logger import get_logger

logger = get_logger("openai_compat")
router = APIRouter(tags=["openai-compat"])


def _extract_last_user(messages: list[dict]) -> str:
    """Return the text of the most recent user message.

    Handles both plain-string content and the list-of-parts content shape.
    """
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            return (content or "").strip()
    return ""


async def _run_pipeline(body: dict) -> tuple[str, str]:
    """Run one turn through the existing chat pipeline. Returns (reply, session_id)."""
    messages = body.get("messages", []) or []
    model = (body.get("model") or "retail").split("/")[-1].strip() or "retail"
    session_id = body.get("user") or body.get("session_id")
    user_message = _extract_last_user(messages) or " "

    chat_req = ChatRequest(
        message=user_message,
        session_id=session_id,
        sector=model,
        src_lang="ENGLISH",  # Chat Bucket handles STT/translation on its side
        lang="ENGLISH",
    )
    resp = await chat_pipeline(chat_req)
    return resp.reply, resp.session_id


@router.get("/v1/models")
async def list_models():
    """Advertise each sector as a selectable model (some platforms probe this)."""
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": s, "object": "model", "created": now, "owned_by": "chat-agent-platform"}
            for s in get_all_sectors()
        ],
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = (body.get("model") or "retail")
    stream = bool(body.get("stream", False))

    reply, session_id = await _run_pipeline(body)
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    logger.info(f"openai_compat model={model} stream={stream} session={session_id} out={reply[:80]}")

    if not stream:
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def event_stream():
        base = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
        }
        # role chunk
        yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
        # content chunks, word by word for a natural typing effect
        words = reply.split(" ")
        for i, word in enumerate(words):
            token = word if i == 0 else " " + word
            yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'content': token}, 'finish_reason': None}]})}\n\n"
        # final chunk
        yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

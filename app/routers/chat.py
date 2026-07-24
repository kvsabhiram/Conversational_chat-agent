import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest, ChatResponse
from app.services.chat_graph import chat_graph
from app.services.memory_manager import memory_manager
from app.utils.helpers import generate_session_id, sanitize_input
from app.utils.logger import get_logger

logger = get_logger("chat")
router = APIRouter(prefix="/api", tags=["chat"])


def _build_initial_state(request: ChatRequest) -> dict:
    # No translate-in step: the LLM reads the user's message directly in
    # whatever language it's written in (see chat_graph.py's docstring).
    sanitized = sanitize_input(request.message)
    return {
        "start_time": time.time(),
        "session_id": request.session_id or generate_session_id(),
        "sector": request.sector,
        "tenant_id": request.tenant_id,
        "src_lang": request.src_lang,
        "user_lang": request.lang,
        "user_message_original": sanitized,
        "user_message": sanitized,
        "is_custom": request.sector.startswith("custom_"),
        "write_memory": True,
        "escalated": False,
        "stream": request.stream,
    }


def _response_from_state(state: dict, session_id: str) -> ChatResponse:
    rag_context = state.get("rag_context")
    return ChatResponse(
        reply=state.get("bot_reply_translated") or state.get("bot_reply", ""),
        session_id=session_id,
        intent=state.get("intent_str"),
        confidence=state.get("confidence"),
        sources=rag_context.sources if rag_context and rag_context.chunks else None,
        escalated=state.get("escalated", False),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    initial_state = _build_initial_state(request)
    session_id = initial_state["session_id"]

    if not request.stream:
        try:
            final_state = await chat_graph.ainvoke(initial_state)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[{session_id}] Pipeline error: {e}")
            raise HTTPException(status_code=503, detail="LLM service unavailable")
        return _response_from_state(final_state, session_id)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"
        try:
            final_state: dict = {}
            async for mode, payload in chat_graph.astream(
                initial_state, stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    yield f"data: {json.dumps(payload)}\n\n"
                elif mode == "values":
                    final_state = payload
            done = _response_from_state(final_state, session_id).model_dump()
            done["type"] = "done"
            yield f"data: {json.dumps(done)}\n\n"
        except HTTPException as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': e.detail})}\n\n"
        except Exception as e:
            logger.error(f"[{session_id}] Streaming pipeline error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'LLM service unavailable'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    await memory_manager.clear(session_id)
    return {"status": "cleared", "session_id": session_id}

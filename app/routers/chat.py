import time
from fastapi import APIRouter, HTTPException
from app.models.schemas import ChatRequest, ChatResponse
from app.services.llm_client import llm_client
from app.utils.helpers import generate_session_id, sanitize_input
from app.utils.logger import get_logger

from app.services.intent_classifier import classify_intent
from app.services.rag_retriever import rag_retriever
from app.services.prompt_builder import build_prompt
from app.services.memory_manager import memory_manager
from app.services.guardrails import check_input, check_output
from app.services.escalation import should_escalate
from app.services.translator import to_english, from_english
from app.models.db_session import save_conversation_log

logger = get_logger("chat")
router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    start_time = time.time()

    user_message_original = sanitize_input(request.message)
    session_id = request.session_id or generate_session_id()
    sector = request.sector
    src_lang = request.src_lang
    user_lang = request.lang

    # Translate user input to English so the rest of the pipeline operates in one language.
    # ENGLISH src skips translation; "auto" or anything else hits the gateway.
    user_message = (
        user_message_original
        if src_lang.upper() == "ENGLISH"
        else await to_english(user_message_original, src_lang=src_lang)
    )

    logger.info(
        f"[{session_id}] sector={sector} src={src_lang} tgt={user_lang} msg={user_message[:80]}..."
    )

    # Input guardrails (run on the English version so regex patterns apply)
    blocked, reason = await check_input(user_message)
    if blocked:
        logger.warning(f"[{session_id}] Input blocked: {reason}")
        reply_text = await from_english(
            "I'm sorry, I can't process that request. Please rephrase your question.",
            user_lang,
        )
        return ChatResponse(reply=reply_text, session_id=session_id)

    is_custom = sector.startswith("custom_")
    intent_result = None
    rag_context = None

    # Get conversation history from Redis
    history = await memory_manager.get_history(session_id)

    if is_custom:
        # Custom persona — use stored prompt directly
        from app.routers.persona import personas
        persona = personas.get(sector)
        if not persona:
            raise HTTPException(404, "Custom persona not found")
        system_prompt = persona["prompt"]
    else:
        # Built-in sector — full pipeline
        intent_result = await classify_intent(user_message, sector)
        logger.info(f"[{session_id}] intent={intent_result.intent} conf={intent_result.confidence}")
        rag_context = await rag_retriever.retrieve(user_message, sector)
        system_prompt = build_prompt(
            sector=sector, intent=intent_result,
            rag_context=rag_context, memory=history,
        )

    # Build messages
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # LLM generation
    try:
        result = await llm_client.chat_completion(
            messages=messages, max_tokens=1024, temperature=0.7,
        )
        bot_reply = result["text"]
    except Exception as e:
        logger.error(f"[{session_id}] LLM error: {e}")
        if should_escalate(error=e):
            reply_text = await from_english(
                "Technical difficulties. Connecting you with a human agent.", user_lang
            )
            return ChatResponse(reply=reply_text, session_id=session_id, escalated=True)
        raise HTTPException(status_code=503, detail="LLM service unavailable")

    # Escalation check for built-in sectors
    if not is_custom and intent_result and should_escalate(intent=intent_result):
        from app.services.escalation import get_escalation_message
        reply_text = await from_english(get_escalation_message(sector), user_lang)
        return ChatResponse(
            reply=reply_text,
            session_id=session_id,
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            escalated=True,
        )

    # Output guardrails (operate on the English reply)
    bot_reply, was_filtered = await check_output(bot_reply, sector if not is_custom else "custom")
    if was_filtered:
        logger.warning(f"[{session_id}] Output filtered")

    # Translate the reply back to the user's language
    bot_reply_translated = await from_english(bot_reply, user_lang)

    # Response (user sees the translated version)
    response = ChatResponse(
        reply=bot_reply_translated,
        session_id=session_id,
        intent=intent_result.intent if intent_result else None,
        confidence=intent_result.confidence if intent_result else None,
        sources=rag_context.sources if rag_context and rag_context.chunks else None,
    )

    # Memory keeps the English versions so future LLM calls have consistent context
    await memory_manager.add_turn(session_id, user_message, bot_reply)

    latency = round((time.time() - start_time) * 1000, 2)
    logger.info(
        f"[{session_id}] in={user_message[:120]} | out={bot_reply[:120]} | "
        f"latency={latency}ms tokens={result.get('tokens_used', 0)}",
        extra={
            "session_id": session_id,
            "sector": sector,
            "tenant_id": request.tenant_id,
            "src_lang": src_lang,
            "tgt_lang": user_lang,
            "input_original": user_message_original,
            "input": user_message,
            "output": bot_reply,
            "output_translated": bot_reply_translated,
            "intent": intent_result.intent if intent_result else None,
            "confidence": intent_result.confidence if intent_result else None,
            "latency_ms": latency,
            "tokens_used": result.get("tokens_used", 0),
            "rag_chunks": rag_context.total_chunks if rag_context else 0,
        },
    )

    await save_conversation_log(
        session_id=session_id,
        tenant_id=request.tenant_id,
        sector=sector,
        user_message=user_message,
        bot_reply=bot_reply,
        intent=intent_result.intent if intent_result else None,
        confidence=intent_result.confidence if intent_result else None,
        latency_ms=latency,
        tokens_used=result.get("tokens_used", 0),
        rag_chunks=rag_context.total_chunks if rag_context else 0,
        escalated=False,
    )

    return response


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    await memory_manager.clear(session_id)
    return {"status": "cleared", "session_id": session_id}

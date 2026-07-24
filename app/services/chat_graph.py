"""Tier-4: chat pipeline as a LangGraph StateGraph, with SSE streaming.

Graph shape (matches ARCHITECTURAL_IMPROVEMENTS.txt's diagram):

    guardrail_in -> [blocked?]
       -> blocked_reply --------------------------------\
       -> load_history -> rag_retrieve -> [is_custom?]    \
            -> persona_prompt   (custom)                   |
            -> classify_intent  (built-in)                  > guardrail_out -> reply_ready -> finalize
       -> build_messages -> llm_call                       |
            (queue-busy / llm-error / intent-escalate -----/
             all short-circuit to a canned bot_reply)

guardrail_out and reply_ready are single nodes every path passes through;
each is a no-op (or a pure copy) when its work already happened upstream —
escalation replies skip guardrail_out entirely, matching the original
pipeline's behavior of never running PII/phrase filtering on canned
system messages; streaming replies are guardrail-checked per-sentence
inline during llm_call, so guardrail_out sees the result already applied.

Language policy: there is no separate translation-service round trip.
The LLM (Gemma) is prompted — via prompt_builder.language_instruction —
to read the user's message and reply directly in the requested language,
since Gemma is fluent enough across ~100 languages that translating as
part of generation beats a translate-in/translate-out pipeline (simpler,
one less external dependency, no double-translation quality loss). See
prompt_builder.py for the exact instruction and CLAUDE.md/README for the
trade-offs (e.g. RAG retrieval and guardrail phrase-matching are still
English-centric, so quality may vary by language — see README).
"""

import re
import time
from typing import Optional, TypedDict

from fastapi import HTTPException
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

from app.models.db_session import save_conversation_log
from app.models.schemas import IntentResult
from app.services.escalation import get_escalation_message, should_escalate
from app.services.guardrails import check_input, check_output
from app.services.intent_classifier import classify_intent
from app.services.llm_client import llm_client
from app.services.memory_manager import memory_manager
from app.services.prompt_builder import BREVITY_RULE, build_prompt, language_instruction
from app.services.queue_manager import queue_manager
from app.services.rag_retriever import RAGResult, rag_retriever
from app.utils import metrics
from app.utils.logger import get_logger

logger = get_logger("chat_graph")

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


class ChatState(TypedDict, total=False):
    start_time: float
    session_id: str
    sector: str
    tenant_id: Optional[str]
    src_lang: str
    user_lang: str
    is_custom: bool
    stream: bool
    user_message_original: str
    user_message: str
    blocked: bool
    block_reason: str
    history: list
    rag_context: Optional[RAGResult]
    intent_result: Optional[IntentResult]
    system_prompt: str
    messages: list
    bot_reply: str
    bot_reply_translated: str
    result: dict
    escalated: bool
    write_memory: bool
    intent_str: Optional[str]
    confidence: Optional[float]


async def _stage_timer(sector: str, stage: str, start: float) -> None:
    metrics.chat_latency_seconds.labels(sector=sector, stage=stage).observe(time.time() - start)


async def node_guardrail_in(state: ChatState) -> dict:
    t0 = time.time()
    blocked, reason = await check_input(state["user_message"])
    if blocked:
        logger.warning(f"[{state['session_id']}] Input blocked: {reason}")
    await _stage_timer(state["sector"], "guardrail_in", t0)
    return {"blocked": blocked, "block_reason": reason}


async def node_blocked_reply(state: ChatState) -> dict:
    return {
        "bot_reply": "I'm sorry, I can't process that request. Please rephrase your question.",
        "escalated": True,
        "write_memory": False,
    }


async def node_load_history(state: ChatState) -> dict:
    history = await memory_manager.get_history(state["session_id"])
    return {"history": history}


async def node_rag_retrieve(state: ChatState) -> dict:
    t0 = time.time()
    rag_context = await rag_retriever.retrieve(state["user_message"], state["sector"])
    await _stage_timer(state["sector"], "rag", t0)
    return {"rag_context": rag_context}


async def node_persona_prompt(state: ChatState) -> dict:
    from app.routers.persona import personas

    persona = personas.get(state["sector"])
    if not persona:
        raise HTTPException(404, "Custom persona not found")

    parts = [
        language_instruction(state["user_lang"], state.get("src_lang", "")),
        BREVITY_RULE,
        persona["prompt"],
    ]
    rag_context = state.get("rag_context")
    if rag_context and rag_context.chunks:
        ctx_text = "\n---\n".join(rag_context.chunks[:3])
        parts.append(
            f"\nRELEVANT INFORMATION FROM KNOWLEDGE BASE:\n{ctx_text}\n"
            "Use the above information to answer the user's question."
        )
    return {"system_prompt": "\n\n".join(parts)}


async def node_classify_intent(state: ChatState) -> dict:
    t0 = time.time()
    intent_result = await classify_intent(state["user_message"], state["sector"])
    logger.info(
        f"[{state['session_id']}] intent={intent_result.intent} conf={intent_result.confidence}"
    )
    system_prompt = build_prompt(
        sector=state["sector"],
        intent=intent_result,
        rag_context=state.get("rag_context"),
        memory=state.get("history"),
        user_lang=state["user_lang"],
        src_lang=state.get("src_lang", ""),
    )
    await _stage_timer(state["sector"], "classify_intent", t0)
    return {"intent_result": intent_result, "system_prompt": system_prompt}


async def node_build_messages(state: ChatState) -> dict:
    messages = [{"role": "system", "content": state["system_prompt"]}]
    messages.extend(state.get("history") or [])
    messages.append({"role": "user", "content": state["user_message"]})
    return {"messages": messages}


async def _flush_sentence(
    sentence: str,
    *,
    guardrail_sector: str,
    writer,
    parts: list,
) -> None:
    filtered, _ = await check_output(sentence, guardrail_sector)
    parts.append(filtered)
    if writer:
        writer({"type": "chunk", "text": filtered})


async def _stream_llm_and_process(state: ChatState) -> str:
    """Consume LLM token deltas, buffering into sentences.

    Each completed sentence is guardrail-filtered and emitted to the
    client via the LangGraph custom stream writer as soon as it's ready.
    No translation step: the LLM is already writing in the requested
    language (see language_instruction() in prompt_builder.py), so this
    only has to buffer for guardrail filtering, not for a second API call.
    """
    writer = get_stream_writer()
    guardrail_sector = "custom" if state["is_custom"] else state["sector"]

    buffer = ""
    parts: list[str] = []

    async for delta in llm_client.astream_chat(
        messages=state["messages"], max_tokens=220, temperature=0.7
    ):
        buffer += delta
        while True:
            match = SENTENCE_BOUNDARY.search(buffer)
            if not match:
                break
            sentence, buffer = buffer[: match.end()], buffer[match.end():]
            await _flush_sentence(sentence, guardrail_sector=guardrail_sector, writer=writer, parts=parts)

    if buffer.strip():
        await _flush_sentence(buffer, guardrail_sector=guardrail_sector, writer=writer, parts=parts)

    return "".join(parts).strip()


async def node_llm_call(state: ChatState) -> dict:
    session_id = state["session_id"]

    slot_ok = await queue_manager.acquire(session_id, timeout=30.0)
    if not slot_ok:
        return {
            "bot_reply": "The service is busy right now. Please try again in a moment.",
            "escalated": True,
            "write_memory": False,
        }

    t0 = time.time()
    try:
        try:
            if state.get("stream"):
                bot_reply = await _stream_llm_and_process(state)
                result = {"text": bot_reply}
            else:
                result = await llm_client.chat_completion(
                    messages=state["messages"], max_tokens=220, temperature=0.7
                )
                bot_reply = result["text"]
            update = {"bot_reply": bot_reply, "result": result}
        except Exception as e:
            logger.error(f"[{session_id}] LLM error: {e}")
            if should_escalate(error=e):
                return {
                    "bot_reply": "Technical difficulties. Connecting you with a human agent.",
                    "escalated": True,
                    "write_memory": False,
                }
            raise HTTPException(status_code=503, detail="LLM service unavailable")
    finally:
        queue_manager.release(session_id)
        await _stage_timer(state["sector"], "llm", t0)

    # Intent-based escalation for built-in sectors — the LLM reply is
    # discarded in favor of the canned escalation message (matches the
    # original chat.py behavior; the LLM is still called either way).
    intent_result = state.get("intent_result")
    if not state["is_custom"] and intent_result and should_escalate(intent=intent_result):
        return {
            "bot_reply": get_escalation_message(state["sector"]),
            "result": result,
            "escalated": True,
            "write_memory": False,
        }

    return update


async def node_guardrail_out(state: ChatState) -> dict:
    if state.get("stream") or state.get("escalated"):
        return {}
    guardrail_sector = "custom" if state["is_custom"] else state["sector"]
    filtered, was_filtered = await check_output(state["bot_reply"], guardrail_sector)
    if was_filtered:
        logger.warning(f"[{state['session_id']}] Output filtered")
    return {"bot_reply": filtered}


async def node_reply_ready(state: ChatState) -> dict:
    """Copy bot_reply into bot_reply_translated.

    Named for the response field, not an action: there's no translation
    call here anymore (see the module docstring) — the LLM already wrote
    the reply in the target language. This just gives finalize/the router
    one stable field to read regardless of which path produced bot_reply.
    """
    return {"bot_reply_translated": state.get("bot_reply", "")}


async def node_finalize(state: ChatState) -> dict:
    session_id = state["session_id"]
    sector = state["sector"]
    latency = round((time.time() - state["start_time"]) * 1000, 2)
    result = state.get("result") or {}
    tokens = result.get("tokens_used", 0)
    rag_context = state.get("rag_context")
    rag_chunks_count = rag_context.total_chunks if rag_context else 0
    intent_result = state.get("intent_result")
    intent_str = intent_result.intent if intent_result else None
    confidence = intent_result.confidence if intent_result else None
    bot_reply = state.get("bot_reply", "")
    bot_reply_translated = state.get("bot_reply_translated") or bot_reply
    escalated = state.get("escalated", False)
    write_memory = state.get("write_memory", True)

    if write_memory and bot_reply:
        await memory_manager.add_turn(session_id, state["user_message"], bot_reply)

    display_out = bot_reply_translated or bot_reply
    logger.info(
        f"[{session_id}] in={state['user_message'][:120]} | out={display_out[:120]} | "
        f"latency={latency}ms tokens={tokens} escalated={escalated}",
        extra={
            "session_id": session_id,
            "sector": sector,
            "tenant_id": state.get("tenant_id"),
            "src_lang": state["src_lang"],
            "tgt_lang": state["user_lang"],
            "input_original": state["user_message_original"],
            "input": state["user_message"],
            "output": bot_reply,
            "output_translated": bot_reply_translated,
            "intent": intent_str,
            "confidence": confidence,
            "latency_ms": latency,
            "tokens_used": tokens,
            "rag_chunks": rag_chunks_count,
            "escalated": escalated,
        },
    )

    await save_conversation_log(
        session_id=session_id,
        tenant_id=state.get("tenant_id"),
        sector=sector,
        user_message=state["user_message"],
        bot_reply=bot_reply or bot_reply_translated,
        intent=intent_str,
        confidence=confidence,
        latency_ms=latency,
        tokens_used=tokens,
        rag_chunks=rag_chunks_count,
        escalated=escalated,
    )

    metrics.chat_requests_total.labels(
        sector=sector, status="escalated" if escalated else "ok"
    ).inc()
    metrics.chat_latency_seconds.labels(sector=sector, stage="total").observe(latency / 1000)

    return {
        "bot_reply_translated": bot_reply_translated,
        "intent_str": intent_str,
        "confidence": confidence,
    }


def _route_after_guardrail_in(state: ChatState) -> str:
    return "blocked" if state.get("blocked") else "continue"


def _route_by_sector_kind(state: ChatState) -> str:
    return "custom" if state["is_custom"] else "builtin"


def _build_graph():
    graph = StateGraph(ChatState)

    graph.add_node("guardrail_in", node_guardrail_in)
    graph.add_node("blocked_reply", node_blocked_reply)
    graph.add_node("load_history", node_load_history)
    graph.add_node("rag_retrieve", node_rag_retrieve)
    graph.add_node("persona_prompt", node_persona_prompt)
    graph.add_node("classify_intent", node_classify_intent)
    graph.add_node("build_messages", node_build_messages)
    graph.add_node("llm_call", node_llm_call)
    graph.add_node("guardrail_out", node_guardrail_out)
    graph.add_node("reply_ready", node_reply_ready)
    graph.add_node("finalize", node_finalize)

    graph.set_entry_point("guardrail_in")
    graph.add_conditional_edges(
        "guardrail_in",
        _route_after_guardrail_in,
        {"blocked": "blocked_reply", "continue": "load_history"},
    )
    graph.add_edge("blocked_reply", "reply_ready")
    graph.add_edge("load_history", "rag_retrieve")
    graph.add_conditional_edges(
        "rag_retrieve",
        _route_by_sector_kind,
        {"custom": "persona_prompt", "builtin": "classify_intent"},
    )
    graph.add_edge("persona_prompt", "build_messages")
    graph.add_edge("classify_intent", "build_messages")
    graph.add_edge("build_messages", "llm_call")
    graph.add_edge("llm_call", "guardrail_out")
    graph.add_edge("guardrail_out", "reply_ready")
    graph.add_edge("reply_ready", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


chat_graph = _build_graph()

"""HTTP-level tests for POST /api/chat's streaming path (Tier-4 streaming)."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.models.schemas import IntentResult
from app.services import chat_graph
from app.services.rag_retriever import RAGResult

AUTH_HEADERS = {"X-API-Key": get_settings().api_secret_key}


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch):
    async def fake_retrieve(query, sector, top_k=3):
        return RAGResult(chunks=[], sources=[], total_chunks=0)

    async def fake_classify_intent(message, sector):
        return IntentResult(intent="general_query", confidence=0.8, sector=sector, params={})

    async def fake_astream_chat(messages, max_tokens=1024, temperature=0.7):
        for delta in ["Hello ", "there, ", "how can I help?"]:
            yield delta

    async def fake_chat_completion(messages, max_tokens=1024, temperature=0.7):
        return {"text": "Hello there.", "tokens_used": 4, "latency_ms": 1.0}

    monkeypatch.setattr(chat_graph.rag_retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(chat_graph, "classify_intent", fake_classify_intent)
    monkeypatch.setattr(chat_graph.llm_client, "astream_chat", fake_astream_chat)
    monkeypatch.setattr(chat_graph.llm_client, "chat_completion", fake_chat_completion)


def _parse_sse(raw_body: str) -> list[dict]:
    events = []
    for block in raw_body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.split("\n"):
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    return events


@pytest.mark.asyncio
async def test_chat_non_streaming_unchanged():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/chat",
            json={"message": "hi there", "sector": "retail"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "Hello there."
        assert "session_id" in data


@pytest.mark.asyncio
async def test_chat_streaming_returns_sse():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/chat",
            json={"message": "hi there", "sector": "retail", "stream": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        events = _parse_sse(resp.text)
        types = [e["type"] for e in events]
        assert types[0] == "start"
        assert "chunk" in types
        assert types[-1] == "done"

        done_event = events[-1]
        assert done_event["reply"]
        assert "session_id" in done_event

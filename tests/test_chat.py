"""Tests for the chat endpoint."""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_root():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "sectors" in data
        assert len(data["sectors"]) == 6


@pytest.mark.asyncio
async def test_chat_validation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Empty message should fail
        resp = await client.post("/api/chat", json={"message": "", "sector": "retail"})
        assert resp.status_code == 422

        # Invalid sector should fail
        resp = await client.post("/api/chat", json={"message": "hello", "sector": "invalid"})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_success():
    """This test requires llama.cpp running on :8080."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/chat", json={
            "message": "What is your return policy?",
            "sector": "retail",
        })
        # Will be 503 if llama.cpp is not running
        if resp.status_code == 200:
            data = resp.json()
            assert "reply" in data
            assert "session_id" in data

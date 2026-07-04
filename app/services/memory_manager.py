"""Phase 3: Session memory manager using Redis.

Stores conversation history per session in Redis with TTL.
Replaces the in-memory dict from Phase 1.
"""

import json
import redis.asyncio as redis
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger("memory")
settings = get_settings()

SESSION_TTL = 3600 * 24  # 24 hours
MAX_TURNS = settings.max_memory_turns


class MemoryManager:
    def __init__(self):
        self.redis: redis.Redis | None = None

    async def connect(self):
        self.redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        logger.info("Redis connected for session memory")

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

    async def get_history(self, session_id: str) -> list[dict]:
        """Get conversation history for a session. Returns [] on any Redis error."""
        if not self.redis:
            return []
        try:
            data = await self.redis.get(self._key(session_id))
        except Exception as e:
            logger.warning(f"Redis get_history failed for {session_id}: {e}")
            return []
        if not data:
            return []
        return json.loads(data)

    async def add_turn(
        self,
        session_id: str,
        user_message: str,
        bot_reply: str,
        metadata: dict | None = None,
    ):
        """Add a conversation turn. Silently no-ops on Redis error."""
        if not self.redis:
            return

        history = await self.get_history(session_id)
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": bot_reply})
        if len(history) > MAX_TURNS * 2:
            history = history[-(MAX_TURNS * 2):]

        try:
            await self.redis.set(
                self._key(session_id), json.dumps(history), ex=SESSION_TTL
            )
        except Exception as e:
            logger.warning(f"Redis add_turn failed for {session_id}: {e}")

    async def clear(self, session_id: str):
        if not self.redis:
            return
        try:
            await self.redis.delete(self._key(session_id))
        except Exception as e:
            logger.warning(f"Redis clear failed for {session_id}: {e}")

    async def get_session_metadata(self, session_id: str) -> dict:
        """Get metadata about a session (turn count, age, etc.)."""
        history = await self.get_history(session_id)
        ttl = await self.redis.ttl(self._key(session_id)) if self.redis else 0
        return {
            "session_id": session_id,
            "turns": len(history) // 2,
            "ttl_seconds": ttl,
        }


# Singleton
memory_manager = MemoryManager()

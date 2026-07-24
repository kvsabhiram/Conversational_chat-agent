"""Phase 3: Request queue manager.

When the GPU is busy, queue incoming requests instead of crashing.
Uses Redis as a simple FIFO queue with concurrency control.
"""

import asyncio
import redis.asyncio as redis
from app.config import get_settings
from app.utils import metrics
from app.utils.logger import get_logger

logger = get_logger("queue")
settings = get_settings()

MAX_CONCURRENT = 4  # Max simultaneous LLM requests (tune based on GPU)


class QueueManager:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self.redis: redis.Redis | None = None
        self.active_requests = 0

    async def connect(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    async def acquire(self, session_id: str, timeout: float = 30.0) -> bool:
        """Wait for a slot to become available.

        Returns True if slot acquired, False if timeout.
        """
        try:
            acquired = await asyncio.wait_for(
                self.semaphore.acquire(), timeout=timeout
            )
            self.active_requests += 1
            metrics.active_llm_slots.set(self.active_requests)
            logger.debug(f"Slot acquired for {session_id}. Active: {self.active_requests}/{MAX_CONCURRENT}")
            return acquired
        except asyncio.TimeoutError:
            logger.warning(f"Queue timeout for {session_id}")
            return False

    def release(self, session_id: str):
        """Release a slot after request completes."""
        self.semaphore.release()
        self.active_requests = max(0, self.active_requests - 1)
        metrics.active_llm_slots.set(self.active_requests)
        logger.debug(f"Slot released for {session_id}. Active: {self.active_requests}/{MAX_CONCURRENT}")

    @property
    def queue_status(self) -> dict:
        return {
            "active_requests": self.active_requests,
            "max_concurrent": MAX_CONCURRENT,
            "available_slots": MAX_CONCURRENT - self.active_requests,
        }


# Singleton
queue_manager = QueueManager()

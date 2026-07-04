"""Phase 3: Rate limiting middleware using slowapi."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import time
from collections import defaultdict
from app.config import get_settings

settings = get_settings()

# Simple in-memory rate limiter (Phase 4: use Redis-backed)
request_counts: dict[str, list[float]] = defaultdict(list)
WINDOW = 60  # seconds
MAX_REQUESTS = 60  # per window


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only rate-limit the chat endpoint
        if not request.url.path.startswith("/api/chat"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        api_key = request.headers.get("X-API-Key", client_ip)
        key = f"rate:{api_key}"

        now = time.time()
        # Clean old entries
        request_counts[key] = [t for t in request_counts[key] if now - t < WINDOW]

        if len(request_counts[key]) >= MAX_REQUESTS:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "retry_after_seconds": WINDOW,
                },
            )

        request_counts[key].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(
            MAX_REQUESTS - len(request_counts[key])
        )
        return response

"""Phase 3: API key authentication middleware."""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import get_settings

settings = get_settings()

# Public endpoints that don't need auth
PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(status_code=401, detail="Missing API key")

        # Phase 4: Validate against tenant database
        # For now, check against a single secret
        if api_key != settings.api_secret_key:
            raise HTTPException(status_code=403, detail="Invalid API key")

        return await call_next(request)

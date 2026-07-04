"""Phase 4: Multi-tenant management router.

Each client (tenant) gets:
- Their own API key
- Their own agent configs per sector
- Isolated conversation history
- Separate knowledge base documents
- Custom rate limits
"""

from fastapi import APIRouter, HTTPException
import uuid
import secrets
from app.utils.logger import get_logger

logger = get_logger("tenants")
router = APIRouter(prefix="/api/tenants", tags=["tenants"])

# In-memory store (Phase 4: PostgreSQL via TenantDB)
tenants: dict[str, dict] = {}


@router.post("/")
async def create_tenant(name: str, sectors: list[str]):
    """Create a new tenant with API key."""
    tenant_id = uuid.uuid4().hex[:12]
    api_key = f"sk-{secrets.token_hex(24)}"

    valid_sectors = {"education", "retail", "medical", "real_estate", "banking", "tourism"}
    invalid = set(sectors) - valid_sectors
    if invalid:
        raise HTTPException(400, f"Invalid sectors: {invalid}")

    tenant = {
        "tenant_id": tenant_id,
        "name": name,
        "api_key": api_key,
        "sectors": sectors,
        "rate_limit": 60,
        "is_active": True,
    }
    tenants[tenant_id] = tenant

    logger.info(f"Tenant created: {name} ({tenant_id})")

    return {
        "tenant_id": tenant_id,
        "api_key": api_key,
        "sectors": sectors,
        "message": "Save your API key — it won't be shown again.",
    }


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: str):
    """Get tenant details (without API key)."""
    tenant = tenants.get(tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    return {k: v for k, v in tenant.items() if k != "api_key"}


@router.get("/")
async def list_tenants():
    """List all tenants."""
    return {
        "tenants": [
            {k: v for k, v in t.items() if k != "api_key"}
            for t in tenants.values()
        ],
        "total": len(tenants),
    }


@router.patch("/{tenant_id}/rate-limit")
async def update_rate_limit(tenant_id: str, rate_limit: int):
    """Update a tenant's rate limit."""
    if tenant_id not in tenants:
        raise HTTPException(404, "Tenant not found")

    tenants[tenant_id]["rate_limit"] = rate_limit
    return {"tenant_id": tenant_id, "rate_limit": rate_limit}


@router.delete("/{tenant_id}")
async def deactivate_tenant(tenant_id: str):
    """Deactivate a tenant (soft delete)."""
    if tenant_id not in tenants:
        raise HTTPException(404, "Tenant not found")

    tenants[tenant_id]["is_active"] = False
    logger.info(f"Tenant deactivated: {tenant_id}")
    return {"tenant_id": tenant_id, "status": "deactivated"}

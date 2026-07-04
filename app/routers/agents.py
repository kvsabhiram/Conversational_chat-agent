"""Phase 2: Agent configuration CRUD router."""

from fastapi import APIRouter, HTTPException
from app.models.schemas import AgentConfig
from app.prompts.base_system import SECTOR_PROMPTS, get_all_sectors
from app.services.intent_classifier import get_intents_for_sector
from app.utils.logger import get_logger

logger = get_logger("agents")
router = APIRouter(prefix="/api/agents", tags=["agents"])

# In-memory store (Phase 4: replaced by PostgreSQL via TenantDB)
custom_agents: dict[str, AgentConfig] = {}


@router.get("/sectors")
async def list_sectors():
    """List all available sectors."""
    return {
        "sectors": get_all_sectors(),
        "total": len(get_all_sectors()),
    }


@router.get("/{sector}")
async def get_agent(sector: str):
    """Get agent config for a sector."""
    if sector not in SECTOR_PROMPTS and sector not in custom_agents:
        raise HTTPException(status_code=404, detail=f"Sector '{sector}' not found")

    if sector in custom_agents:
        return custom_agents[sector]

    return AgentConfig(
        sector=sector,
        name=f"{sector.title()} Agent",
        system_prompt=SECTOR_PROMPTS[sector],
        intents=get_intents_for_sector(sector),
    )


@router.put("/{sector}")
async def update_agent(sector: str, config: AgentConfig):
    """Update or create a custom agent config."""
    custom_agents[sector] = config
    logger.info(f"Agent updated: {sector}")
    return {"status": "updated", "sector": sector}


@router.get("/{sector}/intents")
async def get_intents(sector: str):
    """Get all intents for a sector."""
    intents = get_intents_for_sector(sector)
    if not intents:
        raise HTTPException(status_code=404, detail=f"No intents for sector '{sector}'")
    return {"sector": sector, "intents": intents, "total": len(intents)}

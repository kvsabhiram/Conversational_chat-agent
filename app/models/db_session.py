"""Async SQLAlchemy engine + session for conversation log persistence.

Best-effort: if PostgreSQL is unreachable at startup, logs are skipped
rather than failing every chat request.

Schema is managed by Alembic (see /alembic), not by create_all() — run
`alembic upgrade head` before starting the app (the Dockerfile entrypoint
does this). init_db() only verifies connectivity.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.database import ConversationLogDB
from app.utils.logger import get_logger

logger = get_logger("db")
settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_db_ready = False


async def init_db() -> bool:
    global _db_ready
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        _db_ready = True
        logger.info("PostgreSQL connected; schema managed by Alembic (alembic upgrade head)")
    except Exception as e:
        _db_ready = False
        logger.warning(f"PostgreSQL unavailable, conversation logs disabled: {e}")
    return _db_ready


async def shutdown_db():
    await engine.dispose()


async def save_conversation_log(**fields) -> None:
    if not _db_ready:
        return
    try:
        async with SessionLocal() as session:
            session.add(ConversationLogDB(**fields))
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to write conversation log: {e}")

"""
db/database.py — Async database engine, session factory, and FastAPI dependency.

Changes from original:
  - get_db_session: proper try/except/rollback pattern (no silent data loss)
  - engine: pool_size, max_overflow, pool_timeout, pool_pre_ping configured
  - AsyncSessionLocal exported for sentinel_agent.py direct use
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import sqlalchemy as sa
from fastapi.requests import HTTPConnection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

# ─────────────────────────────────────────────────────────────
# Engine  (pool tuned for production)
# ─────────────────────────────────────────────────────────────

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,  # drop dead connections before checkout
    pool_size=10,  # base connection pool size
    max_overflow=20,  # extra connections allowed under burst load
    pool_timeout=30,  # seconds to wait for a connection before raising
)

# ─────────────────────────────────────────────────────────────
# Session factory
# ─────────────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ─────────────────────────────────────────────────────────────
# FastAPI dependency
# ─────────────────────────────────────────────────────────────


async def get_db_session(connection: HTTPConnection) -> AsyncGenerator[AsyncSession, None]:
    """Provide an AsyncSession with tenant RLS context.

    - Sets PostgreSQL ``app.tenant_id`` local variable so RLS policies fire.
    - Commits on clean exit, rolls back on exception — no silent data loss.
    - Compatible with both HTTP Request and WebSocket connections.
    """
    async with AsyncSessionLocal() as session:
        # Inject tenant context for RLS policies
        tenant_id = getattr(connection.state, "tenant_id", None)
        if tenant_id:
            await session.execute(
                sa.text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

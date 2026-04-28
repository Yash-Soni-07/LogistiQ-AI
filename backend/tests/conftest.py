"""
tests/conftest.py — Shared pytest fixtures for LogistiQ AI test suite.

Design principles
─────────────────
- No live dependencies: SQLite in-memory for DB, fakeredis for Redis,
  AsyncMock for MCP clients and external APIs.
- All fixtures are function-scoped by default (fresh state per test).
- The ``app_client`` fixture uses httpx.AsyncClient with FastAPI's
  ASGI transport — full middleware stack, auth, and routing included.
- Auth tokens are created directly via core.auth functions (no HTTP).
"""

from __future__ import annotations

import asyncio
import os

# Must be set before any app module is imported so settings.TESTING=True
# activates correctly (skips real DB/Redis pings and engine.dispose in lifespan).
os.environ.setdefault("TESTING", "true")

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# ── Test database (SQLite in-memory) ─────────────────────────
_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Force pytest-asyncio to use a single event loop for the entire session.
    This prevents cross-loop RuntimeError with aiosqlite and StaticPool.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()



@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Session-scoped engine so aiosqlite background threads don't cross loops."""
    import aiosqlite  # noqa: F401
    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean SQLite in-memory async session per test.

    Creates all tables fresh for every test function, then drops them.
    """
    from db.models import Base

    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with session_factory() as session:
        yield session

    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)



@pytest_asyncio.fixture(scope="function")
async def redis_mock(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Replace the global redis_client with an in-memory FakeRedis instance."""
    fake = FakeRedis(decode_responses=True)
    # Patch every module that imported redis_client at load time
    import core.redis as _cr
    import billing.usage_tracker as ut
    import agents.gdelt_scanner as gs
    import ml.risk_scorer as rs
    monkeypatch.setattr(_cr, "redis_client", fake)
    monkeypatch.setattr(ut, "redis_client", fake)
    monkeypatch.setattr(gs, "redis_client", fake)
    monkeypatch.setattr(rs, "redis_client", fake)
    yield fake
    await fake.aclose()


# ── MCP mock clients ──────────────────────────────────────────

@pytest.fixture()
def mock_weather_client() -> AsyncMock:
    """MCP weather client returning predictable flood data."""
    client = AsyncMock()
    client.call.return_value = {
        "risk_score": 0.30,
        "risk_level": "LOW",
        "rain_24h_mm": 5.0,
        "elevation_m": 45.0,
        "sources": ["Open-Meteo"],
    }
    return client


@pytest.fixture()
def mock_satellite_client() -> AsyncMock:
    """MCP satellite client returning empty fires and quakes (low risk)."""
    client = AsyncMock()

    async def _satellite_call(tool_name: str, params: dict[str, Any]) -> Any:
        if tool_name == "get_active_fires":
            return {"features": []}
        if tool_name == "get_earthquake_alerts":
            return []
        return {}

    client.call.side_effect = _satellite_call
    return client


@pytest.fixture()
def mock_mcp_clients(mock_weather_client: AsyncMock, mock_satellite_client: AsyncMock) -> dict[str, Any]:
    return {"weather": mock_weather_client, "satellite": mock_satellite_client}


# ── Sample ORM objects ────────────────────────────────────────

@pytest_asyncio.fixture()
async def sample_tenant(db_session: AsyncSession):
    """Insert and return a test Tenant."""
    import uuid
    from db.models import Tenant
    tenant = Tenant(id=str(uuid.uuid4()), name="Test Corp")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture()
async def sample_user(db_session: AsyncSession, sample_tenant):
    """Insert and return an ADMIN User for the test tenant."""
    import uuid
    from core.auth import hash_password
    from db.models import User, UserRole
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=str(sample_tenant.id),
        email="admin@test.com",
        full_name="Test Admin",
        hashed_password=hash_password("TestPass123!"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def sample_operator(db_session: AsyncSession, sample_tenant):
    """Insert and return an OPERATOR User."""
    import uuid
    from core.auth import hash_password
    from db.models import User, UserRole
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=str(sample_tenant.id),
        email="operator@test.com",
        full_name="Test Operator",
        hashed_password=hash_password("TestPass123!"),
        role=UserRole.OPERATOR,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def sample_shipment(db_session: AsyncSession, sample_tenant):
    """Insert and return an IN_TRANSIT Shipment."""
    import uuid
    from db.models import Shipment, ShipmentMode, ShipmentStatus
    shipment = Shipment(
        id=str(uuid.uuid4()),
        tenant_id=str(sample_tenant.id),
        origin="Mumbai",
        destination="Delhi",
        sector="fmcg",
        mode=ShipmentMode.ROAD,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg=5000.0,
    )
    db_session.add(shipment)
    await db_session.commit()
    await db_session.refresh(shipment)
    return shipment


# ── Auth token helpers ────────────────────────────────────────

@pytest.fixture()
def admin_token(sample_user, sample_tenant) -> str:
    from core.auth import create_access_token
    return create_access_token(
        str(sample_user.id), str(sample_tenant.id), "admin"
    )


@pytest.fixture()
def operator_token(sample_operator, sample_tenant) -> str:
    from core.auth import create_access_token
    return create_access_token(
        str(sample_operator.id), str(sample_tenant.id), "operator"
    )


# ── HTTP test client ──────────────────────────────────────────

@pytest_asyncio.fixture()
async def app_client(db_session: AsyncSession, redis_mock: FakeRedis) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP test client backed by the FastAPI app.

    Overrides get_db_session and redis_client so routes use the
    in-memory test fixtures instead of real infrastructure.
    """
    from main import app
    from db.database import get_db_session

    async def _override_db(connection=None):
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()

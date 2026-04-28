"""tests/integration/test_websocket_routes.py — Integration tests for /ws/* endpoints.

Coverage
────────
WS /ws/disruptions          connect + receive connected ACK + ping/pong
WS /ws/dashboard            connect + receive tick + ping/pong
WS /ws/shipments/{id}       connect + receive init message + ping/pong
                            rejected when shipment belongs to different tenant
                            rejected when token is invalid

Architecture notes
──────────────────
FastAPI's TestClient (httpx + starlette.testclient) supports WebSocket testing
via ``client.websocket_connect()``. We use the synchronous ``TestClient`` from
``starlette.testclient`` rather than httpx.AsyncClient because:
  1. TestClient.websocket_connect() is the standard way to test WS in Starlette/FastAPI.
  2. It runs the ASGI app in a background thread, so async route handlers work correctly.
  3. The in-memory DB and auth fixtures are still function-scoped per test.

Token delivery: WS endpoints expect ``?token=<jwt>`` query parameter, NOT
an Authorization header (browser WebSocket API limitation documented in routes).
"""

from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from core.auth import create_access_token, hash_password


# ── Fixture: synchronous TestClient ──────────────────────────
# We patch DB the same way app_client does, but use starlette TestClient
# so websocket_connect() is available.


@pytest.fixture()
def ws_client(db_session, redis_mock):
    """Synchronous Starlette TestClient with DB + Redis overrides."""
    from main import app
    from db.database import get_db_session

    async def _override_db(connection=None):
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


# ── Helper: insert tenant + user, return token ───────────────


async def _create_user_and_token(db_session, email: str, role_str: str = "admin"):
    """Insert a Tenant + User into the test DB and return a JWT token."""
    from db.models import Tenant, User, UserRole

    tenant = Tenant(id=str(uuid.uuid4()), name=f"WSTenant-{email[:6]}")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant.id),
        email=email,
        hashed_password=hash_password("TestPass123!"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), role_str)
    return user, tenant, token


# ── WS /ws/disruptions ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_disruptions_connect_and_ack(ws_client: TestClient, db_session, redis_mock):
    """Connecting to /ws/disruptions sends a 'connected' ACK message."""
    _, _, token = await _create_user_and_token(db_session, "wsdisrupt@test.com")

    with ws_client.websocket_connect(f"/ws/disruptions?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert msg["channel"] == "disruptions"
        assert "tenant_id" in msg
        assert "ts" in msg


@pytest.mark.asyncio
async def test_ws_disruptions_ping_pong(ws_client: TestClient, db_session, redis_mock):
    """Sending 'ping' on /ws/disruptions receives a 'pong' response."""
    _, _, token = await _create_user_and_token(db_session, "wspingdis@test.com")

    with ws_client.websocket_connect(f"/ws/disruptions?token={token}") as ws:
        ws.receive_json()          # consume 'connected' ACK
        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "pong"


@pytest.mark.asyncio
async def test_ws_disruptions_invalid_token_closed(ws_client: TestClient, redis_mock):
    """Invalid JWT on /ws/disruptions → server closes with 1008 Policy Violation."""
    with pytest.raises(Exception):
        # starlette raises WebSocketDisconnect / raises when server rejects
        with ws_client.websocket_connect("/ws/disruptions?token=this.is.not.valid") as ws:
            ws.receive_json()


# ── WS /ws/dashboard ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_dashboard_receives_tick(ws_client: TestClient, db_session, redis_mock):
    """Connecting to /ws/dashboard should receive an initial 'tick' message."""
    _, _, token = await _create_user_and_token(db_session, "wsdash@test.com")

    with ws_client.websocket_connect(f"/ws/dashboard?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "tick"
        assert "ts" in msg
        assert "connections" in msg


@pytest.mark.asyncio
async def test_ws_dashboard_ping_pong(ws_client: TestClient, db_session, redis_mock):
    """Sending 'ping' on /ws/dashboard receives a 'pong' response."""
    _, _, token = await _create_user_and_token(db_session, "wsdashping@test.com")

    with ws_client.websocket_connect(f"/ws/dashboard?token={token}") as ws:
        ws.receive_json()          # consume initial tick
        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "pong"


@pytest.mark.asyncio
async def test_ws_dashboard_invalid_token_rejected(ws_client: TestClient, redis_mock):
    """Invalid token on /ws/dashboard → connection rejected."""
    with pytest.raises(Exception):
        with ws_client.websocket_connect("/ws/dashboard?token=bad.jwt.token") as ws:
            ws.receive_json()


# ── WS /ws/shipments (fleet stream) ─────────────────────────


@pytest.mark.asyncio
async def test_ws_shipments_all_connects_and_sends_feature_collection(ws_client: TestClient, db_session, redis_mock):
    """Connecting to /ws/shipments sends an initial FeatureCollection payload."""
    from db.models import Shipment, ShipmentMode, ShipmentStatus

    _, tenant, token = await _create_user_and_token(db_session, "wsfleet@test.com")

    shipment = Shipment(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant.id),
        origin="Mumbai",
        destination="Delhi",
        sector="fmcg",
        mode=ShipmentMode.ROAD,
        status=ShipmentStatus.IN_TRANSIT,
    )
    db_session.add(shipment)
    await db_session.commit()

    with ws_client.websocket_connect(f"/ws/shipments?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "FeatureCollection"
        assert isinstance(msg["features"], list)


# ── WS /ws/shipments/{id} ────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_shipment_connect_init(ws_client: TestClient, db_session, redis_mock):
    """Connecting to /ws/shipments/{id} sends an 'init' message with shipment state."""
    from db.models import Shipment, ShipmentMode, ShipmentStatus

    user, tenant, token = await _create_user_and_token(db_session, "wsship@test.com")

    # Insert a shipment owned by this tenant
    shipment = Shipment(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant.id),
        origin="Mumbai",
        destination="Delhi",
        sector="fmcg",
        mode=ShipmentMode.ROAD,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg=1000.0,
    )
    db_session.add(shipment)
    await db_session.commit()

    with ws_client.websocket_connect(f"/ws/shipments/{shipment.id}?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "init"
        assert msg["shipment_id"] == shipment.id
        assert msg["status"] == "in_transit"
        assert msg["origin"] == "Mumbai"
        assert msg["destination"] == "Delhi"
        assert "ts" in msg


@pytest.mark.asyncio
async def test_ws_shipment_ping_pong(ws_client: TestClient, db_session, redis_mock):
    """Sending 'ping' on /ws/shipments/{id} receives a 'pong'."""
    from db.models import Shipment, ShipmentMode, ShipmentStatus

    user, tenant, token = await _create_user_and_token(db_session, "wsshipping@test.com")

    shipment = Shipment(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant.id),
        origin="Chennai",
        destination="Bangalore",
        sector="auto",
        mode=ShipmentMode.RAIL,
        status=ShipmentStatus.PENDING,
    )
    db_session.add(shipment)
    await db_session.commit()

    with ws_client.websocket_connect(f"/ws/shipments/{shipment.id}?token={token}") as ws:
        ws.receive_json()          # consume 'init'
        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert "ts" in pong


@pytest.mark.asyncio
async def test_ws_shipment_wrong_tenant_rejected(ws_client: TestClient, db_session, redis_mock):
    """A shipment owned by tenant B rejects a connection from tenant A."""
    from db.models import Shipment, ShipmentMode, ShipmentStatus, Tenant, User, UserRole

    # Create tenant A
    tenant_a = Tenant(id=str(uuid.uuid4()), name="TenantA-WS")
    db_session.add(tenant_a)
    await db_session.flush()
    user_a = db_session.add(User(
        id=str(uuid.uuid4()), tenant_id=str(tenant_a.id),
        email="ws_usera@test.com", hashed_password=hash_password("x"), role=UserRole.ADMIN,
    ))
    await db_session.flush()

    # Create tenant B with a shipment
    tenant_b = Tenant(id=str(uuid.uuid4()), name="TenantB-WS")
    db_session.add(tenant_b)
    await db_session.flush()

    shipment_b = Shipment(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant_b.id),
        origin="Kolkata",
        destination="Patna",
        sector="fmcg",
        mode=ShipmentMode.ROAD,
        status=ShipmentStatus.IN_TRANSIT,
    )
    db_session.add(shipment_b)
    await db_session.commit()

    # Token scoped to tenant A
    from sqlalchemy import select
    from db.models import User as UserModel
    result = await db_session.execute(
        select(UserModel).where(UserModel.email == "ws_usera@test.com")
    )
    user_a_obj = result.scalar_one()
    token_a = create_access_token(str(user_a_obj.id), str(tenant_a.id), "admin")

    # Attempting to connect to tenant B's shipment WS → 1008 Policy Violation
    with pytest.raises(Exception):
        with ws_client.websocket_connect(
            f"/ws/shipments/{shipment_b.id}?token={token_a}"
        ) as ws:
            ws.receive_json()


@pytest.mark.asyncio
async def test_ws_shipment_nonexistent_id_rejected(ws_client: TestClient, db_session, redis_mock):
    """Non-existent shipment ID → WS connection rejected (1008)."""
    _, _, token = await _create_user_and_token(db_session, "wsshipnf@test.com")
    fake_id = str(uuid.uuid4())

    with pytest.raises(Exception):
        with ws_client.websocket_connect(f"/ws/shipments/{fake_id}?token={token}") as ws:
            ws.receive_json()


@pytest.mark.asyncio
async def test_ws_shipment_invalid_token_rejected(ws_client: TestClient, redis_mock):
    """Invalid token on /ws/shipments → connection rejected."""
    fake_id = str(uuid.uuid4())
    with pytest.raises(Exception):
        with ws_client.websocket_connect(
            f"/ws/shipments/{fake_id}?token=garbage.token.here"
        ) as ws:
            ws.receive_json()


# ── ConnectionManager unit-level behaviour ────────────────────


@pytest.mark.asyncio
async def test_connection_manager_broadcast(db_session, redis_mock):
    """ConnectionManager.broadcast_to_channel only sends to the target channel."""
    from api.websocket_routes import ConnectionManager

    mgr = ConnectionManager()
    received: list[dict] = []

    class FakeWS:
        async def send_json(self, data):
            received.append(data)

    ws = FakeWS()
    await mgr.connect(ws, "test:channel:1")  # type: ignore[arg-type]

    # Broadcast to a different channel — should NOT deliver
    await mgr.broadcast_to_channel("test:channel:2", {"type": "nope"})
    assert received == []

    # Broadcast to the correct channel — should deliver
    await mgr.broadcast_to_channel("test:channel:1", {"type": "hit"})
    assert len(received) == 1
    assert received[0]["type"] == "hit"


@pytest.mark.asyncio
async def test_connection_manager_disconnect_cleans_up(db_session, redis_mock):
    """After disconnect, the channel key is removed from the manager."""
    from api.websocket_routes import ConnectionManager

    mgr = ConnectionManager()

    class FakeWS:
        async def send_json(self, data): pass
        async def accept(self): pass

    ws = FakeWS()
    await mgr.connect(ws, "channel:abc")  # type: ignore[arg-type]
    assert "channel:abc" in mgr.active_channels()

    mgr.disconnect(ws, "channel:abc")  # type: ignore[arg-type]
    assert "channel:abc" not in mgr.active_channels()


@pytest.mark.asyncio
async def test_connection_manager_connection_count(db_session, redis_mock):
    """connection_count() returns the total number of active connections."""
    from api.websocket_routes import ConnectionManager

    mgr = ConnectionManager()

    class FakeWS:
        async def send_json(self, data): pass
        async def accept(self): pass

    ws1, ws2 = FakeWS(), FakeWS()
    await mgr.connect(ws1, "ch:1")  # type: ignore[arg-type]
    await mgr.connect(ws2, "ch:2")  # type: ignore[arg-type]
    assert mgr.connection_count() == 2

    mgr.disconnect(ws1, "ch:1")  # type: ignore[arg-type]
    assert mgr.connection_count() == 1

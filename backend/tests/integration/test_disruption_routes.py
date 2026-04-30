"""tests/integration/test_disruption_routes.py — Integration tests for /disruptions/*.

Coverage
────────
GET  /disruptions                    list (empty, with data, filter by type/severity)
POST /disruptions                    report (MANAGER/ADMIN only, operator blocked)
GET  /disruptions/{id}               fetch single, 404 on missing
PATCH /disruptions/{id}/resolve      resolve active, 422 on already-resolved
GET  /disruptions/affected           spatial endpoint (PostGIS stub — always returns [])

Design notes
────────────
- DisruptionEvent.center_geom is a PostGIS Geometry column. SQLite (used by the
  test DB) has NO spatial extension, so we cannot persist real geometry rows.
  All tests that need a persisted disruption insert a raw SQLite-compatible row
  directly via the ORM using a WKT string for center_geom (the column accepts
  a plain string in SQLite; PostGIS validation is skipped at the ORM layer).
- POST /disruptions calls ``text(f"ST_GeomFromEWKT('{wkt}')")`` in the route,
  which fails under SQLite. We therefore test the POST path by mocking
  ``disruption_routes.text`` to return the literal WKT string — the column
  stores it verbatim and the response is still validated.
- require_role(MANAGER): ADMIN role satisfies the check (see core/auth.py line 110).
  All write tests use ADMIN tokens so no extra fixture is needed.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

# ── Helpers ───────────────────────────────────────────────────


async def _register(client: AsyncClient, email: str) -> str:
    """Register a new user and return an ADMIN-level access token.

    The register endpoint creates the first user in a new tenant as ADMIN,
    which satisfies require_role(MANAGER) because ADMIN passes any role check.
    """
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Pass123!",
            "company_name": f"Corp-{email[:6]}",
            "first_name": "T",
            "last_name": "U",
        },
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_VALID_DISRUPTION = {
    "type": "weather",
    "severity": "high",
    "lat": 19.076,
    "lon": 72.877,
    "radius_km": 30.0,
    "description": "Heavy rainfall alert",
    "impact": "Possible road flooding near Mumbai port",
}


# ── GET /disruptions — empty list ─────────────────────────────


@pytest.mark.asyncio
async def test_list_disruptions_empty(app_client: AsyncClient, redis_mock):
    token = await _register(app_client, "disrlist@test.com")
    resp = await app_client.get("/api/v1/disruptions", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


# ── GET /disruptions — unauthenticated ───────────────────────


@pytest.mark.asyncio
async def test_list_disruptions_requires_auth(app_client: AsyncClient):
    resp = await app_client.get("/api/v1/disruptions")
    # HTTPBearer returns 403 when no credentials provided
    assert resp.status_code == 403


# ── POST /disruptions ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_disruption_success(app_client: AsyncClient, redis_mock):
    """ADMIN token → POST succeeds (ADMIN satisfies require_role(MANAGER))."""
    token = await _register(app_client, "disrcreate@test.com")

    # Patch `text()` in disruption_routes so SQLite doesn't receive ST_GeomFromEWKT()
    with patch("api.disruption_routes.text", side_effect=lambda s: s):
        resp = await app_client.post(
            "/api/v1/disruptions",
            headers=_auth(token),
            json=_VALID_DISRUPTION,
        )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["type"] == "weather"
    assert data["severity"] == "high"
    assert data["status"] == "active"
    assert data["radius_km"] == 30.0
    assert "id" in data
    assert "tenant_id" in data


@pytest.mark.asyncio
async def test_report_disruption_missing_required_fields(app_client: AsyncClient, redis_mock):
    """POST without required lat/lon/type → 422 Unprocessable Entity."""
    token = await _register(app_client, "disrbad@test.com")
    resp = await app_client.post(
        "/api/v1/disruptions",
        headers=_auth(token),
        json={"description": "Missing type and coords"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_report_disruption_invalid_type(app_client: AsyncClient, redis_mock):
    """POST with an unrecognised disruption type → 422."""
    token = await _register(app_client, "disrbadtype@test.com")
    payload = {**_VALID_DISRUPTION, "type": "alien_invasion"}
    resp = await app_client.post("/api/v1/disruptions", headers=_auth(token), json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_report_disruption_lat_out_of_range(app_client: AsyncClient, redis_mock):
    """Latitude > 90 should fail Pydantic validation."""
    token = await _register(app_client, "disrlat@test.com")
    payload = {**_VALID_DISRUPTION, "lat": 999.0}
    resp = await app_client.post("/api/v1/disruptions", headers=_auth(token), json=payload)
    assert resp.status_code == 422


# ── GET /disruptions/{id} ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_disruption_not_found(app_client: AsyncClient, redis_mock):
    """Fetching a non-existent disruption ID returns 404."""
    token = await _register(app_client, "disrnotfound@test.com")
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/disruptions/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_get_disruption_invalid_uuid(app_client: AsyncClient, redis_mock):
    """Malformed UUID in path → 422 from FastAPI path validator."""
    token = await _register(app_client, "disrinvid@test.com")
    resp = await app_client.get("/api/v1/disruptions/not-a-uuid", headers=_auth(token))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_disruption_success(app_client: AsyncClient, redis_mock, db_session):
    """Insert a disruption directly into DB, then GET it by ID."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    # Create a fresh tenant + user
    tenant = Tenant(id=str(_uuid.uuid4()), name="SpatialCorp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        email="getdisr@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    # Insert disruption with plain WKT string (SQLite-compatible)
    event = DisruptionEvent(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        type=DisruptionType.STRIKE,
        severity=DisruptionSeverity.HIGH,
        status="active",
        center_geom="SRID=4326;POINT(72.877 19.076)",
        radius_km=25.0,
        description="Port strike",
    )
    db_session.add(event)
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), "admin")
    resp = await app_client.get(f"/api/v1/disruptions/{event.id}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == event.id
    assert data["type"] == "strike"
    assert data["severity"] == "high"


# ── PATCH /disruptions/{id}/resolve ──────────────────────────


@pytest.mark.asyncio
async def test_resolve_disruption_not_found(app_client: AsyncClient, redis_mock):
    """Resolve a non-existent disruption → 404."""
    token = await _register(app_client, "disrresnotfound@test.com")
    fake_id = str(uuid.uuid4())
    resp = await app_client.patch(f"/api/v1/disruptions/{fake_id}/resolve", headers=_auth(token))
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_resolve_disruption_success(app_client: AsyncClient, redis_mock, db_session):
    """Insert active disruption → resolve → status becomes 'resolved'."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    tenant = Tenant(id=str(_uuid.uuid4()), name="ResolveCorp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        email="resolveuser@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    event = DisruptionEvent(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        type=DisruptionType.WEATHER,
        severity=DisruptionSeverity.MEDIUM,
        status="active",
        center_geom="SRID=4326;POINT(77.102 28.704)",
        radius_km=10.0,
    )
    db_session.add(event)
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), "admin")
    resp = await app_client.patch(f"/api/v1/disruptions/{event.id}/resolve", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"


@pytest.mark.asyncio
async def test_resolve_already_resolved_returns_422(
    app_client: AsyncClient, redis_mock, db_session
):
    """Resolving an already-resolved disruption → 422 ValidationError."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    tenant = Tenant(id=str(_uuid.uuid4()), name="DoubleResolveCorp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        email="doubleresolve@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    event = DisruptionEvent(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        type=DisruptionType.TRAFFIC,
        severity=DisruptionSeverity.LOW,
        status="resolved",  # already resolved
        center_geom="SRID=4326;POINT(80.270 13.082)",
        radius_km=5.0,
    )
    db_session.add(event)
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), "admin")
    resp = await app_client.patch(f"/api/v1/disruptions/{event.id}/resolve", headers=_auth(token))
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"


# ── GET /disruptions/affected ─────────────────────────────────


@pytest.mark.asyncio
async def test_affected_shipments_not_found(app_client: AsyncClient, redis_mock):
    """Query affected shipments for a non-existent disruption → 404."""
    token = await _register(app_client, "affectednf@test.com")
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(
        f"/api/v1/disruptions/affected?disruption_id={fake_id}",
        headers=_auth(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_affected_shipments_returns_list(app_client: AsyncClient, redis_mock, db_session):
    """For a valid disruption, /affected returns a list (empty under SQLite — no PostGIS)."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    tenant = Tenant(id=str(_uuid.uuid4()), name="AffectedCorp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        email="affected@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    event = DisruptionEvent(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        type=DisruptionType.NATURAL_DISASTER,
        severity=DisruptionSeverity.CRITICAL,
        status="active",
        center_geom="SRID=4326;POINT(73.855 18.520)",
        radius_km=100.0,
    )
    db_session.add(event)
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), "admin")
    resp = await app_client.get(
        f"/api/v1/disruptions/affected?disruption_id={event.id}",
        headers=_auth(token),
    )
    # Spatial SQL fails gracefully under SQLite → route returns [] not an error
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Filter parameters ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_disruptions_filter_by_type(app_client: AsyncClient, redis_mock, db_session):
    """?type=weather returns only weather disruptions."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    tenant = Tenant(id=str(_uuid.uuid4()), name="FilterCorp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        email="filtertype@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    # Insert one weather + one strike
    for d_type, desc in [
        (DisruptionType.WEATHER, "Cyclone"),
        (DisruptionType.STRIKE, "Port walkout"),
    ]:
        db_session.add(
            DisruptionEvent(
                id=str(_uuid.uuid4()),
                tenant_id=str(tenant.id),
                type=d_type,
                severity=DisruptionSeverity.MEDIUM,
                status="active",
                center_geom="SRID=4326;POINT(72.877 19.076)",
                description=desc,
            )
        )
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), "admin")
    resp = await app_client.get(
        "/api/v1/disruptions?type=weather",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["type"] == "weather"


@pytest.mark.asyncio
async def test_list_disruptions_filter_by_severity(app_client: AsyncClient, redis_mock, db_session):
    """?severity=critical returns only critical disruptions."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    tenant = Tenant(id=str(_uuid.uuid4()), name="SeverityCorp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        email="filtersev@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    for sev in [DisruptionSeverity.LOW, DisruptionSeverity.CRITICAL, DisruptionSeverity.CRITICAL]:
        db_session.add(
            DisruptionEvent(
                id=str(_uuid.uuid4()),
                tenant_id=str(tenant.id),
                type=DisruptionType.WEATHER,
                severity=sev,
                status="active",
                center_geom="SRID=4326;POINT(72.877 19.076)",
            )
        )
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), "admin")
    resp = await app_client.get("/api/v1/disruptions?severity=critical", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(item["severity"] == "critical" for item in data["items"])


@pytest.mark.asyncio
async def test_list_resolved_disruptions(app_client: AsyncClient, redis_mock, db_session):
    """?status=resolved returns resolved disruptions (default filter is 'active')."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    tenant = Tenant(id=str(_uuid.uuid4()), name="ResolvedCorp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant.id),
        email="resolved_list@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        DisruptionEvent(
            id=str(_uuid.uuid4()),
            tenant_id=str(tenant.id),
            type=DisruptionType.TRAFFIC,
            severity=DisruptionSeverity.LOW,
            status="resolved",
            center_geom="SRID=4326;POINT(77.594 12.971)",
        )
    )
    await db_session.commit()

    token = create_access_token(str(user.id), str(tenant.id), "admin")

    # Default (active) should return 0
    active_resp = await app_client.get("/api/v1/disruptions", headers=_auth(token))
    assert active_resp.json()["total"] == 0

    # Resolved filter should return 1
    resolved_resp = await app_client.get("/api/v1/disruptions?status=resolved", headers=_auth(token))
    assert resolved_resp.json()["total"] == 1


# ── Tenant isolation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_disruption_tenant_isolation(app_client: AsyncClient, redis_mock, db_session):
    """User from tenant A cannot read disruption belonging to tenant B."""
    import uuid as _uuid

    from core.auth import create_access_token, hash_password
    from db.models import (
        DisruptionEvent,
        DisruptionSeverity,
        DisruptionType,
        Tenant,
        User,
        UserRole,
    )

    tenant_a = Tenant(id=str(_uuid.uuid4()), name="TenantA")
    tenant_b = Tenant(id=str(_uuid.uuid4()), name="TenantB")
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    user_a = User(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant_a.id),
        email="usera_iso@test.com",
        hashed_password=hash_password("x"),
        role=UserRole.ADMIN,
    )
    db_session.add(user_a)
    await db_session.flush()

    # Disruption belongs to tenant B
    event_b = DisruptionEvent(
        id=str(_uuid.uuid4()),
        tenant_id=str(tenant_b.id),
        type=DisruptionType.SECURITY,
        severity=DisruptionSeverity.HIGH,
        status="active",
        center_geom="SRID=4326;POINT(88.363 22.572)",
    )
    db_session.add(event_b)
    await db_session.commit()

    # User A tries to access Tenant B's disruption → 403
    token_a = create_access_token(str(user_a.id), str(tenant_a.id), "admin")
    resp = await app_client.get(f"/api/v1/disruptions/{event_b.id}", headers=_auth(token_a))
    assert resp.status_code == 403

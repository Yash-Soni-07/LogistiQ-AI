"""tests/integration/test_simulation_routes.py — Integration tests for /simulation/demo."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Pass123!",
            "company_name": "Demo Logistics",
            "first_name": "Demo",
            "last_name": "User",
        },
    )
    return resp.json()["access_token"]


async def _create_demo_shipments(client: AsyncClient, token: str, count: int) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    routes = [
        ("Mumbai", "Delhi"),
        ("Bangalore", "Chennai"),
        ("Kolkata", "Patna"),
        ("Hyderabad", "Pune"),
        ("Ahmedabad", "Jaipur"),
        ("Surat", "Nagpur"),
        ("Lucknow", "Kanpur"),
        ("Bhopal", "Visakhapatnam"),
        ("Vadodara", "Thane"),
    ]
    modes = ["road", "air", "sea"]
    sectors = ["tech", "pharma", "retail"]

    for idx in range(count):
        origin, destination = routes[idx % len(routes)]
        await client.post(
            "/api/v1/shipments",
            headers=headers,
            json={
                "origin": origin,
                "destination": destination,
                "sector": sectors[idx % len(sectors)],
                "mode": modes[idx % len(modes)],
            },
        )


@pytest.mark.asyncio
async def test_simulation_demo_requires_minimum_shipments(
    app_client: AsyncClient,
    admin_token: str,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await app_client.post("/api/v1/simulation/demo", headers=headers)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "validation_error"
    assert body["field"] == "shipments"


@pytest.mark.asyncio
async def test_simulation_demo_starts_and_resets_selected_shipments(app_client: AsyncClient):
    token = await _register_and_login(app_client, "sim-start@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    await _create_demo_shipments(app_client, token, count=9)

    resp = await app_client.post(
        "/api/v1/simulation/demo",
        headers=headers,
        params={"speed_multiplier": 50000},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "started"
    assert body["selected_shipments"] == 9
    assert body["mode_distribution"] == {"road": 3, "air": 3, "sea": 3}
    selected_ids = set(body["selected_shipment_ids"])

    shipments_resp = await app_client.get("/api/v1/shipments?limit=20", headers=headers)
    assert shipments_resp.status_code == 200
    items = shipments_resp.json()["items"]
    selected = [item for item in items if item["id"] in selected_ids]
    assert len(selected) == 9
    assert all(item["status"] in {"in_transit", "delivered"} for item in selected)
    assert all(item["risk_score"] == 0.0 for item in selected)

    mode_counts = {"road": 0, "air": 0, "sea": 0}
    for item in selected:
        if item["mode"] in mode_counts:
            mode_counts[item["mode"]] += 1
    assert mode_counts == {"road": 3, "air": 3, "sea": 3}


@pytest.mark.asyncio
async def test_simulation_demo_auto_seeds_in_non_testing_mode(
    app_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from core.config import settings

    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    token = await _register_and_login(app_client, "sim-seeded@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    before_resp = await app_client.get("/api/v1/shipments?limit=20", headers=headers)
    assert before_resp.status_code == 200
    existing_count = len(before_resp.json()["items"])

    resp = await app_client.post(
        "/api/v1/simulation/demo",
        headers=headers,
        params={"speed_multiplier": 50000},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "started"
    assert body["selected_shipments"] == 9
    assert body["seeded_shipments"] == max(0, 9 - existing_count)

    shipments_resp = await app_client.get("/api/v1/shipments?limit=20", headers=headers)
    assert shipments_resp.status_code == 200
    assert len(shipments_resp.json()["items"]) >= 9


@pytest.mark.asyncio
async def test_simulation_demo_returns_already_running_for_same_tenant(app_client: AsyncClient):
    token = await _register_and_login(app_client, "sim-running@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    await _create_demo_shipments(app_client, token, count=9)

    first = await app_client.post(
        "/api/v1/simulation/demo",
        headers=headers,
        params={"speed_multiplier": 100},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "started"

    second = await app_client.post("/api/v1/simulation/demo", headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "already_running"

    # Ensure the long-running task is replaced by a fast run for test cleanup.
    third = await app_client.post(
        "/api/v1/simulation/demo",
        headers=headers,
        params={"restart": True, "speed_multiplier": 50000},
    )
    assert third.status_code == 200
    assert third.json()["status"] == "started"

"""tests/integration/test_shipment_routes.py — Integration tests for /shipments + /carriers."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str, role_override=None) -> str:
    """Register a user and return an access token."""
    reg = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "Pass123!",
            "company_name": "Test Corp",
            "first_name": "T",
            "last_name": "U",
        },
    )
    return reg.json()["access_token"]


# ── /shipments ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_shipments_empty(app_client: AsyncClient):
    token = await _register_and_login(app_client, "list@test.com")
    resp = await app_client.get("/shipments", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_create_shipment_success(app_client: AsyncClient):
    token = await _register_and_login(app_client, "create_ship@test.com")
    resp = await app_client.post(
        "/shipments",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "origin": "Mumbai",
            "destination": "Delhi",
            "sector": "fmcg",
            "mode": "road",
            "weight_kg": 2000,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["origin"] == "Mumbai"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_create_and_list_shipment(app_client: AsyncClient):
    token = await _register_and_login(app_client, "list2@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    await app_client.post(
        "/shipments",
        headers=headers,
        json={
            "origin": "Chennai",
            "destination": "Bangalore",
            "sector": "auto",
            "mode": "rail",
        },
    )
    resp = await app_client.get("/shipments", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_get_shipment_by_id(app_client: AsyncClient):
    token = await _register_and_login(app_client, "getship@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await app_client.post(
        "/shipments",
        headers=headers,
        json={
            "origin": "Pune",
            "destination": "Nagpur",
            "sector": "pharma",
            "mode": "road",
        },
    )
    ship_id = create_resp.json()["id"]
    resp = await app_client.get(f"/shipments/{ship_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == ship_id


@pytest.mark.asyncio
async def test_get_shipment_not_found(app_client: AsyncClient):
    token = await _register_and_login(app_client, "notfound@test.com")
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(
        f"/shipments/{fake_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_update_shipment_status(app_client: AsyncClient):
    token = await _register_and_login(app_client, "update@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await app_client.post(
        "/shipments",
        headers=headers,
        json={
            "origin": "Delhi",
            "destination": "Jaipur",
            "sector": "fmcg",
            "mode": "road",
        },
    )
    ship_id = create_resp.json()["id"]
    resp = await app_client.patch(
        f"/shipments/{ship_id}", headers=headers, json={"status": "in_transit"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_transit"


@pytest.mark.asyncio
async def test_cancel_shipment(app_client: AsyncClient):
    token = await _register_and_login(app_client, "cancel@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await app_client.post(
        "/shipments",
        headers=headers,
        json={
            "origin": "Kolkata",
            "destination": "Siliguri",
            "sector": "fmcg",
            "mode": "rail",
        },
    )
    ship_id = create_resp.json()["id"]
    resp = await app_client.delete(f"/shipments/{ship_id}", headers=headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_filter_shipments_by_status(app_client: AsyncClient):
    token = await _register_and_login(app_client, "filter@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    # Create two shipments, update one
    r1 = await app_client.post(
        "/shipments",
        headers=headers,
        json={"origin": "A", "destination": "B", "sector": "x", "mode": "road"},
    )
    await app_client.post(
        "/shipments",
        headers=headers,
        json={"origin": "C", "destination": "D", "sector": "x", "mode": "road"},
    )
    await app_client.patch(
        f"/shipments/{r1.json()['id']}", headers=headers, json={"status": "in_transit"}
    )

    resp = await app_client.get("/shipments?status=in_transit", headers=headers)
    assert resp.json()["total"] == 1


# ── /carriers ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_carrier(app_client: AsyncClient):
    token = await _register_and_login(app_client, "carrier@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await app_client.post("/carriers", headers=headers, json={"name": "BlueDart"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "BlueDart"

    list_resp = await app_client.get("/carriers", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_duplicate_carrier_conflict(app_client: AsyncClient):
    token = await _register_and_login(app_client, "carrier2@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    await app_client.post("/carriers", headers=headers, json={"name": "DTDC"})
    resp = await app_client.post("/carriers", headers=headers, json={"name": "DTDC"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "conflict"

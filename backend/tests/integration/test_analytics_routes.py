"""tests/integration/test_analytics_routes.py — Integration tests for /analytics/*."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _setup(client: AsyncClient, email: str) -> tuple[str, dict]:
    """Register, create 3 shipments (2 pending, 1 in_transit), return (token, headers)."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Pass123!",
            "company_name": "Corp",
            "first_name": "A",
            "last_name": "B",
        },
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(3):
        await client.post(
            "/api/v1/shipments",
            headers=headers,
            json={
                "origin": f"City{i}",
                "destination": "Delhi",
                "sector": "fmcg",
                "mode": "road",
            },
        )
    return token, headers


@pytest.mark.asyncio
async def test_summary_has_correct_keys(app_client: AsyncClient, redis_mock):
    token = (
        await app_client.post(
            "/api/v1/auth/register",
            json={
                "email": "summary@test.com",
                "password": "Pass123!",
                "company_name": "Corp",
                "first_name": "S",
                "last_name": "U",
            },
        )
    ).json()["access_token"]
    resp = await app_client.get(
        "/api/v1/analytics/summary", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "total_shipments",
        "delivered",
        "in_transit",
        "delayed",
        "on_time_rate_pct",
        "active_disruptions",
    ):
        assert key in data, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_summary_counts_shipments(app_client: AsyncClient, redis_mock):
    _, headers = await _setup(app_client, "sumcount@test.com")
    resp = await app_client.get("/api/v1/analytics/summary", headers=headers)
    assert resp.json()["total_shipments"] == 3


@pytest.mark.asyncio
async def test_by_status_returns_list(app_client: AsyncClient, redis_mock):
    _, headers = await _setup(app_client, "bystatus@test.com")
    resp = await app_client.get("/api/v1/analytics/shipments/by-status", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    statuses = [item["status"] for item in resp.json()]
    assert "pending" in statuses


@pytest.mark.asyncio
async def test_by_mode_returns_list(app_client: AsyncClient, redis_mock):
    _, headers = await _setup(app_client, "bymode@test.com")
    resp = await app_client.get("/api/v1/analytics/shipments/by-mode", headers=headers)
    assert resp.status_code == 200
    modes = [item["mode"] for item in resp.json()]
    assert "road" in modes


@pytest.mark.asyncio
async def test_usage_stats_endpoint(app_client: AsyncClient, redis_mock):
    reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "usage@test.com",
            "password": "Pass123!",
            "company_name": "Corp",
            "first_name": "U",
            "last_name": "S",
        },
    )
    token = reg.json()["access_token"]
    resp = await app_client.get(
        "/api/v1/analytics/usage", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "monthly_totals" in data
    assert "today" in data
    assert "tenant_id" in data


@pytest.mark.asyncio
async def test_risk_heatmap_returns_list(app_client: AsyncClient, redis_mock):
    reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "heatmap@test.com",
            "password": "Pass123!",
            "company_name": "Corp",
            "first_name": "H",
            "last_name": "M",
        },
    )
    token = reg.json()["access_token"]
    resp = await app_client.get(
        "/api/v1/analytics/risk/heatmap", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_disruption_trend_returns_list(app_client: AsyncClient, redis_mock):
    reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "trend@test.com",
            "password": "Pass123!",
            "company_name": "Corp",
            "first_name": "T",
            "last_name": "R",
        },
    )
    token = reg.json()["access_token"]
    resp = await app_client.get(
        "/api/v1/analytics/disruptions/trend?days=7", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

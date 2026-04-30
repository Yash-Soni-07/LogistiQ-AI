"""tests/integration/test_billing_routes.py — Integration tests for /billing/*."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _admin_token(client: AsyncClient, email: str) -> str:
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Pass123!",
            "company_name": "Corp",
            "first_name": "B",
            "last_name": "L",
        },
    )
    return reg.json()["access_token"]


@pytest.mark.asyncio
async def test_billing_status_no_subscription(app_client: AsyncClient, redis_mock):
    token = await _admin_token(app_client, "bstatus@test.com")
    resp = await app_client.get("/api/v1/billing/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_tier"] == "starter"
    assert data["status"] in ("trialing", "no_subscription")


@pytest.mark.asyncio
async def test_subscribe_dev_mode_no_razorpay_key(app_client: AsyncClient, redis_mock, monkeypatch):
    """Without RAZORPAY_KEY_ID, subscribe completes in dev mode (no payment gateway)."""
    from core import config as cfg

    monkeypatch.setattr(cfg.settings, "RAZORPAY_KEY_ID", None)
    monkeypatch.setattr(cfg.settings, "RAZORPAY_KEY_SECRET", None)

    token = await _admin_token(app_client, "subscribe@test.com")
    resp = await app_client.post(
        "/api/v1/billing/subscribe",
        headers={"Authorization": f"Bearer {token}"},
        json={"plan_tier": "starter", "trial_days": 14},
    )
    assert resp.status_code == 201
    assert "plan_tier" in resp.json()


@pytest.mark.asyncio
async def test_webhook_no_razorpay_secret_returns_400(app_client: AsyncClient, monkeypatch):
    """Webhook without RAZORPAY_WEBHOOK_SECRET should return 400."""
    from core import config as cfg

    monkeypatch.setattr(cfg.settings, "RAZORPAY_WEBHOOK_SECRET", None)

    resp = await app_client.post(
        "/api/v1/billing/webhook",
        content=b'{"event":"payment.captured"}',
        headers={"X-Razorpay-Signature": "badsig", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(app_client: AsyncClient, monkeypatch):
    """Valid Razorpay secret but bad HMAC signature → 400."""
    from core import config as cfg

    monkeypatch.setattr(cfg.settings, "RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")

    resp = await app_client.post(
        "/api/v1/billing/webhook",
        content=b'{"event":"payment.captured"}',
        headers={"X-Razorpay-Signature": "invalidsig", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancel_without_subscription_returns_422(app_client: AsyncClient, redis_mock):
    token = await _admin_token(app_client, "cancel422@test.com")
    resp = await app_client.post(
        "/api/v1/billing/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"


@pytest.mark.asyncio
async def test_portal_endpoint_removed(app_client: AsyncClient, redis_mock):
    """Razorpay has no customer portal — endpoint is gone."""
    token = await _admin_token(app_client, "portal422@test.com")
    resp = await app_client.get(
        "/api/v1/billing/portal",
        headers={"Authorization": f"Bearer {token}"},
    )
    # endpoint removed → 404
    assert resp.status_code == 404

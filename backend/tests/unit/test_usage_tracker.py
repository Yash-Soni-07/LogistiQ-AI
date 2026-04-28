"""tests/unit/test_usage_tracker.py — Unit tests for billing/usage_tracker.py."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from billing.usage_tracker import (
    _tier_limit,
    check_limit,
    get_daily_breakdown,
    get_monthly_usage,
    record_event,
)


# ── record_event ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_event_increments_monthly_counter(redis_mock):
    await record_event("tenant-1", "mcp_call")
    month = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    key = f"usage:tenant-1:mcp_call:{month}"
    value = await redis_mock.get(key)
    assert value == "1"


@pytest.mark.asyncio
async def test_record_event_increments_by_quantity(redis_mock):
    await record_event("tenant-1", "mcp_call", quantity=5)
    month = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    key = f"usage:tenant-1:mcp_call:{month}"
    value = await redis_mock.get(key)
    assert value == "5"


@pytest.mark.asyncio
async def test_record_event_accumulates(redis_mock):
    await record_event("tenant-1", "shipment_created")
    await record_event("tenant-1", "shipment_created")
    await record_event("tenant-1", "shipment_created")
    month = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    key = f"usage:tenant-1:shipment_created:{month}"
    value = await redis_client_get(redis_mock, key)
    assert int(value) == 3


async def redis_client_get(redis_mock, key):
    return await redis_mock.get(key)


@pytest.mark.asyncio
async def test_record_event_fire_and_forget_on_redis_error(monkeypatch):
    """Redis errors are swallowed — no exception propagated."""
    from billing import usage_tracker
    from unittest.mock import MagicMock, AsyncMock

    # Create a mock that raises when used as async context manager
    bad_pipeline = MagicMock()
    bad_pipeline.__aenter__ = AsyncMock(side_effect=ConnectionError("Redis down"))
    bad_pipeline.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(usage_tracker.redis_client, "pipeline", lambda **kw: bad_pipeline)
    # Should not raise
    await record_event("tenant-X", "mcp_call")



# ── get_monthly_usage ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_monthly_usage_empty(redis_mock):
    result = await get_monthly_usage("tenant-empty")
    assert all(v == 0 for v in result.values())
    assert "mcp_call" in result


@pytest.mark.asyncio
async def test_get_monthly_usage_after_events(redis_mock):
    await record_event("tenant-2", "mcp_call", quantity=3)
    await record_event("tenant-2", "ai_decision", quantity=2)
    result = await get_monthly_usage("tenant-2")
    assert result["mcp_call"] == 3
    assert result["ai_decision"] == 2
    assert result["shipment_created"] == 0


# ── get_daily_breakdown ───────────────────────────────────────

@pytest.mark.asyncio
async def test_get_daily_breakdown_empty(redis_mock):
    result = await get_daily_breakdown("tenant-daily")
    assert result == {}


@pytest.mark.asyncio
async def test_get_daily_breakdown_after_event(redis_mock):
    await record_event("tenant-daily2", "alert_sent", quantity=7)
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    result = await get_daily_breakdown("tenant-daily2", today)
    assert result.get("alert_sent", 0) == 7


# ── check_limit ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_limit_under_cap(redis_mock):
    result = await check_limit("tenant-limit", "mcp_call", "starter")
    assert result["allowed"] is True
    assert result["overage"] == 0
    assert result["current"] == 0


@pytest.mark.asyncio
async def test_check_limit_over_cap_still_allowed(redis_mock):
    """Soft cap — still allowed but overage is reported."""
    # Starter limit for mcp_call is 500
    month = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    await redis_mock.set(f"usage:tenant-over:mcp_call:{month}", "600")
    result = await check_limit("tenant-over", "mcp_call", "starter")
    assert result["allowed"] is True    # soft cap
    assert result["overage"] == 100
    assert result["current"] == 600


# ── _tier_limit ───────────────────────────────────────────────

def test_tier_limit_pro_is_10x_starter():
    starter = _tier_limit("mcp_call", "starter")
    pro = _tier_limit("mcp_call", "pro")
    assert pro == starter * 10


def test_tier_limit_enterprise_is_huge():
    import sys
    enterprise = _tier_limit("mcp_call", "enterprise")
    assert enterprise > 1_000_000


def test_tier_limit_unknown_tier_defaults_to_starter():
    unknown = _tier_limit("mcp_call", "unknown_tier")
    starter = _tier_limit("mcp_call", "starter")
    assert unknown == starter

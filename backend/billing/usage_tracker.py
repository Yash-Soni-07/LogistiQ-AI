"""
billing/usage_tracker.py — Metered billing event recorder for LogistiQ AI.

Tracks API-usage signals that feed into generic metered billing and our own
internal analytics.  All writes are fire-and-forget (best-effort) — a Redis
or DB failure must never break the primary request path.

Events tracked (stored in Redis sorted-sets + persisted to SubscriptionEvent):
  - mcp_call          : each MCP tool invocation (billable per call on pro/enterprise)
  - ai_decision       : each decision agent run
  - shipment_created  : new shipment ingestion
  - route_optimised   : VRP solver invocation
  - alert_sent        : FCM push notification sent

Redis key scheme
────────────────
  usage:{tenant_id}:{event_type}:{YYYY-MM}   → INCR counter (expires after 90 days)
  usage:{tenant_id}:daily:{YYYY-MM-DD}        → hash {event_type: count}

The monthly counter is what gets reported to the Billing Provider for
overages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from core.redis import redis_client

log = structlog.get_logger(__name__)

# ── Tier usage limits (free soft-caps before overage kicks in) ──
_MONTHLY_FREE_LIMITS: dict[str, int] = {
    "mcp_call": 500,
    "ai_decision": 50,
    "shipment_created": 100,
    "route_optimised": 20,
    "alert_sent": 200,
}

_REDIS_TTL_SECONDS = 90 * 24 * 3600  # 90 days


# ─────────────────────────────────────────────────────────────
# Core recording function
# ─────────────────────────────────────────────────────────────


async def record_event(
    tenant_id: str,
    event_type: str,
    *,
    quantity: int = 1,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a billable usage event for a tenant.

    Fire-and-forget — errors are logged at WARNING and swallowed so the
    calling request is never affected.

    Parameters
    ----------
    tenant_id  : The tenant UUID string.
    event_type : One of the tracked event names (e.g. ``"mcp_call"``).
    quantity   : How many units to record (default 1).
    metadata   : Optional extra context stored in the daily hash.
    """
    now = datetime.now(tz=UTC)
    month_key = f"usage:{tenant_id}:{event_type}:{now.strftime('%Y-%m')}"
    daily_key = f"usage:{tenant_id}:daily:{now.strftime('%Y-%m-%d')}"

    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            pipe.incrby(month_key, quantity)
            pipe.expire(month_key, _REDIS_TTL_SECONDS)
            pipe.hincrby(daily_key, event_type, quantity)
            pipe.expire(daily_key, 7 * 24 * 3600)  # daily hash kept 7 days
            await pipe.execute()

        log.debug(
            "usage.recorded",
            tenant_id=tenant_id,
            event_type=event_type,
            quantity=quantity,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "usage.record_failed",
            tenant_id=tenant_id,
            event_type=event_type,
            error=str(exc),
        )


# ─────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────


async def get_monthly_usage(tenant_id: str, month: str | None = None) -> dict[str, int]:
    """Return usage counts per event type for the given month.

    Parameters
    ----------
    tenant_id : Tenant UUID string.
    month     : ``"YYYY-MM"`` format.  Defaults to the current month.

    Returns
    -------
    Dict mapping event_type → count for all known event types.
    """
    if month is None:
        month = datetime.now(tz=UTC).strftime("%Y-%m")

    results: dict[str, int] = {}
    try:
        keys = [f"usage:{tenant_id}:{et}:{month}" for et in _MONTHLY_FREE_LIMITS]
        values = await redis_client.mget(*keys)
        for event_type, raw in zip(_MONTHLY_FREE_LIMITS.keys(), values, strict=False):
            results[event_type] = int(raw) if raw else 0
    except Exception as exc:  # noqa: BLE001
        log.warning("usage.get_monthly_failed", tenant_id=tenant_id, error=str(exc))

    return results


async def get_daily_breakdown(tenant_id: str, date: str | None = None) -> dict[str, int]:
    """Return today's (or specified date's) event breakdown.

    Parameters
    ----------
    date : ``"YYYY-MM-DD"`` format.  Defaults to today UTC.
    """
    if date is None:
        date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    daily_key = f"usage:{tenant_id}:daily:{date}"
    try:
        raw = await redis_client.hgetall(daily_key)
        return {k: int(v) for k, v in raw.items()}
    except Exception as exc:  # noqa: BLE001
        log.warning("usage.get_daily_failed", tenant_id=tenant_id, error=str(exc))
        return {}


async def check_limit(
    tenant_id: str,
    event_type: str,
    plan_tier: str = "starter",
) -> dict[str, Any]:
    """Check whether a tenant has reached their soft-cap for an event type.

    Returns a dict with:
      - ``allowed``     : bool — whether the action should be permitted
      - ``current``     : int  — current monthly count
      - ``limit``       : int  — soft-cap for this tier
      - ``overage``     : int  — units over the cap (0 if under)
    """
    limit = _tier_limit(event_type, plan_tier)
    month = datetime.now(tz=UTC).strftime("%Y-%m")
    month_key = f"usage:{tenant_id}:{event_type}:{month}"

    try:
        raw = await redis_client.get(month_key)
        current = int(raw) if raw else 0
    except Exception as exc:  # noqa: BLE001
        log.warning("usage.check_limit_failed", tenant_id=tenant_id, error=str(exc))
        current = 0

    overage = max(0, current - limit)
    return {
        "allowed": True,  # soft-cap — always allowed; overage is billed via provider
        "current": current,
        "limit": limit,
        "overage": overage,
        "event_type": event_type,
        "plan_tier": plan_tier,
    }


# ─────────────────────────────────────────────────────────────
# Internal tier multiplier
# ─────────────────────────────────────────────────────────────


def _tier_limit(event_type: str, plan_tier: str) -> int:
    """Return the soft-cap for an event type on a given plan tier.

    Multipliers:
      starter     → 1× base limit
      pro         → 10× base limit
      enterprise  → unlimited (sys.maxsize)
    """
    import sys

    base = _MONTHLY_FREE_LIMITS.get(event_type, 100)
    multipliers = {"starter": 1, "pro": 10, "enterprise": sys.maxsize // base}
    return base * multipliers.get(plan_tier.lower(), 1)

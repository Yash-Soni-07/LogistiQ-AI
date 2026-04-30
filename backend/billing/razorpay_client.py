"""
billing/razorpay_client.py — Async wrapper around the Razorpay Python SDK.

Design decisions
────────────────
- Razorpay SDK calls are synchronous. Every call is wrapped in
  ``asyncio.to_thread()`` so FastAPI routes remain non-blocking.
- Fail-safe: if RAZORPAY_KEY_ID is not set (dev/CI), every method logs a
  warning and returns a safe None sentinel rather than crashing. This lets the
  rest of the codebase import billing freely without a live Razorpay account.
- All Razorpay exceptions are caught and re-raised as ``ExternalServiceError``
  so the global handler in main.py returns a clean 502.
- Webhook signature is verified with HMAC-SHA256 using RAZORPAY_WEBHOOK_SECRET.

Plan tiers map to Razorpay Plan IDs stored in RAZORPAY_*_PLAN_ID settings.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
from typing import Any

import structlog

from core.config import settings
from core.exceptions import ExternalServiceError

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Lazy client initialisation
# ─────────────────────────────────────────────────────────────

_client: Any = None


def _get_client() -> Any:
    """Return a configured razorpay.Client or None when keys are absent."""
    global _client
    if _client is not None:
        return _client
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        log.warning(
            "razorpay.not_configured",
            hint="Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env to enable billing",
        )
        return None
    try:
        import razorpay as _rp

        _client = _rp.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        log.info("razorpay.initialised")
        return _client
    except ImportError:
        log.error("razorpay.import_failed", hint="Run: uv add razorpay")
        return None


# ─────────────────────────────────────────────────────────────
# Internal helper: run sync SDK call off the event loop
# ─────────────────────────────────────────────────────────────


async def _run(fn, *args: Any, **kwargs: Any) -> Any:
    """Execute a synchronous Razorpay SDK call in a thread pool."""
    try:
        return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))
    except Exception as exc:
        log.error("razorpay.api_error", error=str(exc), type=type(exc).__name__)
        raise ExternalServiceError("Razorpay", message=str(exc)) from exc


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


async def create_customer(*, email: str, name: str, tenant_id: str) -> str | None:
    """Create a Razorpay Customer and return the customer id.

    Returns None in dev mode (keys absent).
    """
    rp = _get_client()
    if rp is None:
        log.warning("razorpay.create_customer.skipped", email=email)
        return None
    data = await _run(
        rp.customer.create,
        {
            "name": name,
            "email": email,
            "notes": {"tenant_id": tenant_id},
        },
    )
    log.info("razorpay.customer_created", customer_id=data["id"], tenant_id=tenant_id)
    return data["id"]


async def create_subscription(
    *,
    customer_id: str,
    tier: str,
    trial_days: int = 14,
) -> dict[str, Any] | None:
    """Create a Razorpay Subscription for the given plan tier.

    Razorpay subscriptions are linked to a Plan ID configured in settings.
    Returns the subscription dict or None in dev mode.
    """
    rp = _get_client()
    if rp is None:
        log.warning("razorpay.create_subscription.skipped", customer_id=customer_id, tier=tier)
        return None

    plan_id = _plan_id_for_tier(tier)
    if not plan_id:
        raise ExternalServiceError(
            "Razorpay",
            message=f"No Razorpay plan ID configured for tier '{tier}'. "
            "Set RAZORPAY_{STARTER,PRO,ENTERPRISE}_PLAN_ID in .env.",
        )

    sub = await _run(
        rp.subscription.create,
        {
            "plan_id": plan_id,
            "customer_notify": 1,
            "quantity": 1,
            "total_count": 12,  # 12 billing cycles
            "start_at": None,  # start immediately
            "notes": {"tenant_id": customer_id, "tier": tier},
            "offer_id": None,
        },
    )
    log.info(
        "razorpay.subscription_created",
        subscription_id=sub["id"],
        customer_id=customer_id,
        tier=tier,
        status=sub["status"],
    )
    return dict(sub)


async def cancel_subscription(
    *, subscription_id: str, at_period_end: bool = True
) -> dict[str, Any] | None:
    """Cancel a Razorpay subscription.

    ``at_period_end=True`` uses ``cancel_at_cycle_end=1`` (Razorpay default).
    Returns the updated subscription dict or None in dev mode.
    """
    rp = _get_client()
    if rp is None:
        log.warning("razorpay.cancel_subscription.skipped", subscription_id=subscription_id)
        return None

    sub = await _run(
        rp.subscription.cancel,
        subscription_id,
        {"cancel_at_cycle_end": 1 if at_period_end else 0},
    )
    log.info(
        "razorpay.subscription_cancelled", subscription_id=subscription_id, status=sub["status"]
    )
    return dict(sub)


async def change_plan(*, subscription_id: str, new_tier: str) -> dict[str, Any] | None:
    """Upgrade / downgrade a subscription to a new plan tier.

    Uses Razorpay's subscription update endpoint to swap the plan.
    Returns the updated subscription dict or None in dev mode.
    """
    rp = _get_client()
    if rp is None:
        log.warning(
            "razorpay.change_plan.skipped", subscription_id=subscription_id, new_tier=new_tier
        )
        return None

    plan_id = _plan_id_for_tier(new_tier)
    if not plan_id:
        raise ExternalServiceError("Razorpay", message=f"No plan ID for tier '{new_tier}'")

    sub = await _run(rp.subscription.update, subscription_id, {"plan_id": plan_id})
    log.info("razorpay.plan_changed", subscription_id=subscription_id, new_tier=new_tier)
    return dict(sub)


def verify_webhook_signature(payload: bytes, signature: str) -> dict[str, Any]:
    """Verify a Razorpay webhook payload using HMAC-SHA256.

    Raises ExternalServiceError on missing secret or bad signature.
    Returns the parsed JSON event on success.
    """
    import json

    if not settings.RAZORPAY_WEBHOOK_SECRET:
        raise ExternalServiceError("Razorpay", message="RAZORPAY_WEBHOOK_SECRET not configured")

    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature or ""):
        raise ExternalServiceError("Razorpay", message="Invalid webhook signature")

    try:
        return json.loads(payload)
    except ValueError as exc:
        raise ExternalServiceError("Razorpay", message="Malformed webhook payload") from exc


# ─────────────────────────────────────────────────────────────
# Internal: plan-ID lookup
# ─────────────────────────────────────────────────────────────


def _plan_id_for_tier(tier: str) -> str | None:
    mapping = {
        "starter": getattr(settings, "RAZORPAY_STARTER_PLAN_ID", None),
        "pro": getattr(settings, "RAZORPAY_PRO_PLAN_ID", None),
        "enterprise": getattr(settings, "RAZORPAY_ENTERPRISE_PLAN_ID", None),
    }
    return mapping.get(tier.lower())

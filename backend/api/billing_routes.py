"""
api/billing_routes.py — Razorpay subscription management + webhook handler.

Endpoints
─────────
GET    /billing/status          Current subscription status for the tenant
POST   /billing/subscribe       Start a Razorpay subscription
POST   /billing/cancel          Cancel subscription (at cycle end)
POST   /billing/change-plan     Upgrade / downgrade plan tier
POST   /billing/webhook         Razorpay webhook receiver (no auth, HMAC verified)
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.razorpay_client import (
    cancel_subscription,
    change_plan,
    create_customer,
    create_subscription,
    verify_webhook_signature,
)
from billing.usage_tracker import record_event
from core.auth import get_current_user, require_role
from core.exceptions import ExternalServiceError, ValidationError
from core.schemas import BillingStatusRead, ChangePlanRequest, SubscribeRequest
from db.database import get_db_session
from db.models import SubscriptionEvent, Tenant, User, UserRole

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


# ─────────────────────────────────────────────────────────────
# Tenant helper
# ─────────────────────────────────────────────────────────────

async def _get_tenant(user: User, db: AsyncSession) -> Tenant:
    return (
        await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    ).scalar_one()


async def _latest_event(user: User, db: AsyncSession) -> SubscriptionEvent | None:
    return (
        await db.execute(
            select(SubscriptionEvent)
            .where(SubscriptionEvent.tenant_id == user.tenant_id)
            .order_by(SubscriptionEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@router.get("/status", response_model=BillingStatusRead)
async def billing_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return the tenant's current subscription info."""
    latest = await _latest_event(user, db)
    if not latest:
        return {"plan_tier": "starter", "status": "trialing", "razorpay_customer_id": None, "details": {}}

    details = latest.details or {}
    return {
        "plan_tier": details.get("tier", "starter"),
        "status": latest.event_type,
        "razorpay_customer_id": details.get("razorpay_customer_id"),
        "details": details,
    }


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: SubscribeRequest,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Create a Razorpay customer + subscription for the tenant."""
    tenant = await _get_tenant(user, db)
    latest = await _latest_event(user, db)

    # Idempotency: reuse existing Razorpay customer id if already created
    razorpay_customer_id = (latest.details or {}).get("razorpay_customer_id") if latest else None
    if not razorpay_customer_id:
        razorpay_customer_id = await create_customer(
            email=user.email,
            name=tenant.name,
            tenant_id=str(user.tenant_id),
        )

    sub = await create_subscription(
        customer_id=razorpay_customer_id or "dev_customer",
        tier=body.plan_tier,
        trial_days=body.trial_days,
    )

    event = SubscriptionEvent(
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        event_type="subscribed",
        details={
            "tier": body.plan_tier,
            "razorpay_customer_id": razorpay_customer_id,
            "subscription_id": (sub or {}).get("id"),
            "status": (sub or {}).get("status", "created"),
        },
    )
    db.add(event)
    await db.commit()

    log.info("billing.subscribed", tenant_id=str(user.tenant_id), tier=body.plan_tier)
    return {"message": "Subscription created", "plan_tier": body.plan_tier, "subscription": sub}


@router.post("/cancel")
async def cancel(
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Cancel the current subscription at cycle end."""
    latest = await _latest_event(user, db)
    sub_id = (latest.details or {}).get("subscription_id") if latest else None
    if not sub_id:
        raise ValidationError("No active subscription found", field="subscription_id")

    result = await cancel_subscription(subscription_id=sub_id, at_period_end=True)

    db.add(SubscriptionEvent(
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        event_type="cancelled",
        details={"subscription_id": sub_id, "cancel_at_cycle_end": True},
    ))
    await db.commit()

    log.info("billing.cancelled", tenant_id=str(user.tenant_id), sub_id=sub_id)
    return {"message": "Subscription will cancel at cycle end", "subscription": result}


@router.post("/change-plan")
async def change_plan_route(
    body: ChangePlanRequest,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Upgrade or downgrade to a new plan tier."""
    latest = await _latest_event(user, db)
    sub_id = (latest.details or {}).get("subscription_id") if latest else None
    if not sub_id:
        raise ValidationError("No active subscription found", field="subscription_id")

    result = await change_plan(subscription_id=sub_id, new_tier=body.plan_tier)

    db.add(SubscriptionEvent(
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        event_type="plan_changed",
        details={"subscription_id": sub_id, "new_tier": body.plan_tier},
    ))
    await db.commit()

    log.info("billing.plan_changed", tenant_id=str(user.tenant_id), new_tier=body.plan_tier)
    return {"message": f"Plan changed to {body.plan_tier}", "subscription": result}


# ─────────────────────────────────────────────────────────────
# Razorpay webhook — no auth, payload verified by HMAC-SHA256
# ─────────────────────────────────────────────────────────────

@router.post("/webhook", include_in_schema=False)
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
) -> Response:
    """
    Receives and processes Razorpay webhook events.

    Handled event types:
      - subscription.activated
      - subscription.completed
      - subscription.cancelled
      - payment.captured
      - payment.failed
    """
    payload = await request.body()

    try:
        event = verify_webhook_signature(payload, x_razorpay_signature or "")
    except ExternalServiceError as exc:
        log.warning("razorpay.webhook.rejected", reason=exc.message)
        return Response(content=exc.message, status_code=400)

    event_type: str = event.get("event", "")
    payload_data: dict = event.get("payload", {})
    sub_obj: dict = payload_data.get("subscription", {}).get("entity", {})
    payment_obj: dict = payload_data.get("payment", {}).get("entity", {})
    tenant_id: str | None = (sub_obj.get("notes") or payment_obj.get("notes") or {}).get("tenant_id")

    log.info("razorpay.webhook.received", event_type=event_type, tenant_id=tenant_id)

    handled = {
        "subscription.activated",
        "subscription.completed",
        "subscription.cancelled",
        "payment.captured",
        "payment.failed",
    }

    if event_type in handled and tenant_id:
        db.add(SubscriptionEvent(
            tenant_id=tenant_id,
            user_id="00000000-0000-0000-0000-000000000000",  # system actor
            event_type=event_type.replace(".", "_"),
            details={
                "razorpay_event_id": event.get("id"),
                "subscription_id": sub_obj.get("id"),
                "payment_id": payment_obj.get("id"),
                "status": sub_obj.get("status") or payment_obj.get("status"),
                "tier": (sub_obj.get("notes") or {}).get("tier"),
            },
        ))
        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("razorpay.webhook.db_write_failed", error=str(exc))

    return Response(content="ok", status_code=200)

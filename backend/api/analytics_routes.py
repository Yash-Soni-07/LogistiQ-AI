"""
api/analytics_routes.py — Read-only aggregated analytics for LogistiQ AI.

All queries are tenant-isolated (RLS) and return pre-aggregated data
suitable for dashboard cards and charts.

Endpoints
─────────
GET /analytics/summary          High-level KPIs (total, on-time %, delayed %)
GET /analytics/shipments/by-status   Breakdown by ShipmentStatus
GET /analytics/shipments/by-mode     Breakdown by ShipmentMode
GET /analytics/disruptions/trend     Daily disruption count for last N days
GET /analytics/risk/heatmap          Top risky route segments (from Redis cache)
GET /analytics/usage                 API usage stats for current month
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.usage_tracker import get_daily_breakdown, get_monthly_usage
from core.auth import get_current_user
from core.redis import redis_client
from db.database import get_db_session
from db.models import (
    DisruptionEvent,
    Shipment,
    ShipmentStatus,
    User,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
async def summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """KPI cards: total shipments, on-time rate, delayed count, active disruptions."""
    tid = str(user.tenant_id)

    # Shipment counts
    count_q = select(
        func.count().label("total"),
        func.sum(case((Shipment.status == ShipmentStatus.DELIVERED, 1), else_=0)).label(
            "delivered"
        ),
        func.sum(case((Shipment.status == ShipmentStatus.DELAYED, 1), else_=0)).label("delayed"),
        func.sum(case((Shipment.status == ShipmentStatus.IN_TRANSIT, 1), else_=0)).label(
            "in_transit"
        ),
        func.sum(case((Shipment.status == ShipmentStatus.CANCELLED, 1), else_=0)).label(
            "cancelled"
        ),
    ).where(Shipment.tenant_id == tid)
    row = (await db.execute(count_q)).one()

    # On-time rate: delivered shipments where actual_delivery <= estimated_delivery
    on_time_q = select(func.count()).where(
        Shipment.tenant_id == tid,
        Shipment.status == ShipmentStatus.DELIVERED,
        Shipment.actual_delivery <= Shipment.estimated_delivery,
    )
    on_time = (await db.execute(on_time_q)).scalar_one() or 0

    # Active disruptions
    disruption_count = (
        await db.execute(
            select(func.count()).where(
                DisruptionEvent.tenant_id == tid,
                DisruptionEvent.status == "active",
            )
        )
    ).scalar_one()

    total = row.total or 0
    delivered = row.delivered or 0
    on_time_pct = round((on_time / delivered * 100) if delivered else 0.0, 1)

    return {
        "total_shipments": total,
        "delivered": delivered,
        "in_transit": row.in_transit or 0,
        "delayed": row.delayed or 0,
        "cancelled": row.cancelled or 0,
        "on_time_rate_pct": on_time_pct,
        "active_disruptions": disruption_count,
    }


@router.get("/shipments/by-status")
async def shipments_by_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Shipment count grouped by status — for donut/bar charts."""
    q = (
        select(Shipment.status, func.count().label("count"))
        .where(Shipment.tenant_id == str(user.tenant_id))
        .group_by(Shipment.status)
        .order_by(func.count().desc())
    )
    rows = (await db.execute(q)).all()
    return [{"status": r.status.value, "count": r.count} for r in rows]


@router.get("/shipments/by-mode")
async def shipments_by_mode(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Shipment count grouped by transport mode."""
    q = (
        select(Shipment.mode, func.count().label("count"))
        .where(Shipment.tenant_id == str(user.tenant_id))
        .group_by(Shipment.mode)
        .order_by(func.count().desc())
    )
    rows = (await db.execute(q)).all()
    return [
        {"mode": r.mode.value if hasattr(r.mode, "value") else r.mode, "count": r.count}
        for r in rows
    ]


@router.get("/disruptions/trend")
async def disruption_trend(
    days: int = Query(14, ge=1, le=90, description="Number of past days to include"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Daily disruption event count for the last N days, grouped by type."""
    since = datetime.now(tz=UTC) - timedelta(days=days)

    # func.date() truncates timestamps to YYYY-MM-DD and is supported by both
    # SQLite (tests) and PostgreSQL (production) without any raw SQL or dialect
    # detection — it is standard SQL-92 that all major engines implement.
    day_expr = func.date(DisruptionEvent.created_at).label("day")

    q = (
        select(
            day_expr,
            DisruptionEvent.type.label("type"),
            func.count().label("count"),
        )
        .where(DisruptionEvent.tenant_id == str(user.tenant_id))
        .where(DisruptionEvent.created_at >= since)
        .group_by(day_expr, DisruptionEvent.type)
        .order_by(day_expr)
    )
    rows = (await db.execute(q)).all()
    return [{"day": str(r.day), "type": r.type, "count": r.count} for r in rows]


@router.get("/risk/heatmap")
async def risk_heatmap(
    top_n: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Top-N riskiest route segments computed by the risk_scorer.

    Pulls from Redis keys: risk:{lat}:{lon}:{date}
    Returns sorted by composite risk_score descending.
    """
    # Scan for all risk keys for this process (not tenant-specific — geo data is shared)
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    pattern = f"risk:*:*:{today}"

    results: list[dict[str, Any]] = []
    try:
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=200)
            for key in keys:
                import json

                raw = await redis_client.get(key)
                if raw:
                    try:
                        data = json.loads(raw)
                        results.append(data)
                    except Exception:  # noqa: BLE001
                        log.debug("analytics.risk_heatmap.bad_key", key=key)
            if cursor == 0:
                break

        results.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
        return results[:top_n]
    except Exception as exc:  # noqa: BLE001
        log.warning("analytics.risk_heatmap_failed", error=str(exc))
        return []


@router.get("/usage")
async def usage_stats(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Current-month API usage counters from Redis usage tracker."""
    monthly = await get_monthly_usage(str(user.tenant_id))
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    daily = await get_daily_breakdown(str(user.tenant_id), today)
    return {
        "tenant_id": str(user.tenant_id),
        "month": datetime.now(tz=UTC).strftime("%Y-%m"),
        "monthly_totals": monthly,
        "today": daily,
    }

"""
api/disruption_routes.py — Disruption event management for LogistiQ AI.

Endpoints
─────────
GET    /disruptions               list active disruptions
POST   /disruptions               manually report (MANAGER+)
GET    /disruptions/{id}          fetch one
PATCH  /disruptions/{id}/resolve  mark resolved (MANAGER+)
GET    /disruptions/affected      shipments spatially intersecting a disruption
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_role
from core.exceptions import NotFoundError, TenantIsolationError, ValidationError
from core.schemas import DisruptionCreate, DisruptionRead, PaginatedResponse
from db.database import get_db_session
from db.models import DisruptionEvent, DisruptionSeverity, DisruptionType, User, UserRole

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/disruptions", tags=["disruptions"])


def _check_tenant(row: DisruptionEvent, user: User) -> None:
    if str(row.tenant_id) != str(user.tenant_id):
        raise TenantIsolationError(tenant_id=str(user.tenant_id))


@router.get("", response_model=PaginatedResponse)
async def list_disruptions(
    disruption_type: DisruptionType | None = Query(None, alias="type"),
    severity: DisruptionSeverity | None = Query(None),
    status: str | None = Query(None, description="active | resolved"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    q = select(DisruptionEvent).where(DisruptionEvent.tenant_id == user.tenant_id)
    cq = select(func.count()).select_from(DisruptionEvent).where(DisruptionEvent.tenant_id == user.tenant_id)

    filter_status = status or "active"
    q = q.where(DisruptionEvent.status == filter_status)
    cq = cq.where(DisruptionEvent.status == filter_status)

    if disruption_type:
        q = q.where(DisruptionEvent.type == disruption_type)
        cq = cq.where(DisruptionEvent.type == disruption_type)
    if severity:
        q = q.where(DisruptionEvent.severity == severity)
        cq = cq.where(DisruptionEvent.severity == severity)

    q = q.order_by(DisruptionEvent.created_at.desc()).offset(offset).limit(limit)
    total = (await db.execute(cq)).scalar_one()
    rows = (await db.execute(q)).scalars().all()
    return {"total": total, "offset": offset, "limit": limit, "items": [DisruptionRead.model_validate(r) for r in rows]}


@router.post("", response_model=DisruptionRead, status_code=201)
async def report_disruption(
    body: DisruptionCreate,
    user: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> DisruptionEvent:
    geom_wkt = f"SRID=4326;POINT({body.lon} {body.lat})"
    event = DisruptionEvent(
        tenant_id=str(user.tenant_id),
        type=body.type,
        severity=body.severity,
        status="active",
        center_geom=text(f"ST_GeomFromEWKT('{geom_wkt}')"),
        radius_km=body.radius_km,
        description=body.description,
        impact=body.impact,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    log.info("disruption.reported", id=str(event.id), type=body.type.value, tenant_id=str(user.tenant_id))
    return event


@router.get("/affected", response_model=list[dict[str, Any]])
async def affected_shipments(
    disruption_id: UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Shipments whose route segments fall within the disruption radius (PostGIS)."""
    event = (await db.execute(select(DisruptionEvent).where(DisruptionEvent.id == str(disruption_id)))).scalar_one_or_none()
    if not event:
        raise NotFoundError("DisruptionEvent", str(disruption_id))
    _check_tenant(event, user)

    try:
        radius_m = (event.radius_km or 50.0) * 1000
        sql = text("""
            SELECT DISTINCT s.id, s.origin, s.destination, s.status, s.mode
            FROM shipments s
            JOIN route_segments rs ON rs.shipment_id = s.id
            WHERE s.tenant_id = :tid
              AND ST_DWithin(rs.geom::geography, :center::geography, :radius_m)
            ORDER BY s.id LIMIT 50
        """)
        result = await db.execute(sql, {"tid": str(user.tenant_id), "center": f"SRID=4326;{event.center_geom}", "radius_m": radius_m})
        return [dict(r) for r in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("disruptions.spatial_query_failed", error=str(exc))
        return []


@router.get("/{disruption_id}", response_model=DisruptionRead)
async def get_disruption(
    disruption_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DisruptionEvent:
    row = (await db.execute(select(DisruptionEvent).where(DisruptionEvent.id == str(disruption_id)))).scalar_one_or_none()
    if not row:
        raise NotFoundError("DisruptionEvent", str(disruption_id))
    _check_tenant(row, user)
    return row


@router.patch("/{disruption_id}/resolve", response_model=DisruptionRead)
async def resolve_disruption(
    disruption_id: UUID,
    user: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> DisruptionEvent:
    row = (await db.execute(select(DisruptionEvent).where(DisruptionEvent.id == str(disruption_id)))).scalar_one_or_none()
    if not row:
        raise NotFoundError("DisruptionEvent", str(disruption_id))
    _check_tenant(row, user)
    if row.status == "resolved":
        raise ValidationError("Disruption is already resolved", field="status")
    row.status = "resolved"
    await db.commit()
    await db.refresh(row)
    log.info("disruption.resolved", id=str(disruption_id), by=str(user.id))
    return row

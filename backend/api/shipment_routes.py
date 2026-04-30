"""
api/shipment_routes.py — Shipment CRUD + carrier management for LogistiQ AI.

All routes are tenant-isolated via PostgreSQL RLS (SET LOCAL app.tenant_id
is applied by get_db_session) and require at minimum OPERATOR role.

Endpoints
─────────
GET    /shipments            list (with cursor-based pagination)
POST   /shipments            create
GET    /shipments/{id}       fetch one
PATCH  /shipments/{id}       update status / fields
DELETE /shipments/{id}       soft-delete (sets status=CANCELLED)

GET    /carriers             list carriers for tenant
POST   /carriers             create carrier
GET    /carriers/{id}        fetch one carrier
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.usage_tracker import record_event
from core.auth import get_current_user, require_role
from core.exceptions import ConflictError, NotFoundError, ValidationError
from core.schemas import (
    CarrierCreate,
    CarrierRead,
    PaginatedResponse,
    ShipmentCreate,
    ShipmentRead,
    ShipmentUpdate,
)
from db.database import get_db_session
from db.models import (
    Carrier,
    Shipment,
    ShipmentMode,
    ShipmentStatus,
    User,
    UserRole,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/shipments", tags=["shipments"])
carrier_router = APIRouter(prefix="/carriers", tags=["carriers"])


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _assert_tenant(resource_tenant_id: Any, user: User) -> None:
    """Guard: resource must belong to the requesting user's tenant."""
    if str(resource_tenant_id) != str(user.tenant_id):
        from core.exceptions import TenantIsolationError

        raise TenantIsolationError(tenant_id=str(user.tenant_id))


# ─────────────────────────────────────────────────────────────
# Shipment routes
# ─────────────────────────────────────────────────────────────


@router.get("", response_model=PaginatedResponse)
async def list_shipments(
    status: ShipmentStatus | None = Query(None, description="Filter by status"),
    mode: ShipmentMode | None = Query(None, description="Filter by transport mode"),
    limit: int = Query(20, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """List shipments for the authenticated tenant with optional filters."""
    q = select(Shipment).where(Shipment.tenant_id == user.tenant_id)
    count_q = select(func.count()).select_from(Shipment).where(Shipment.tenant_id == user.tenant_id)

    if status:
        q = q.where(Shipment.status == status)
        count_q = count_q.where(Shipment.status == status)
    if mode:
        q = q.where(Shipment.mode == mode)
        count_q = count_q.where(Shipment.mode == mode)

    q = q.order_by(Shipment.created_at.desc()).offset(offset).limit(limit)

    total = (await db.execute(count_q)).scalar_one()
    rows = (await db.execute(q)).scalars().all()

    log.info("shipments.listed", tenant_id=str(user.tenant_id), count=len(rows))
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [ShipmentRead.model_validate(r) for r in rows],
    }


@router.post("", response_model=ShipmentRead, status_code=201)
async def create_shipment(
    body: ShipmentCreate,
    user: User = Depends(require_role(UserRole.OPERATOR)),
    db: AsyncSession = Depends(get_db_session),
) -> Shipment:
    """Create a new shipment for the tenant."""
    # Validate carrier belongs to tenant if provided
    if body.carrier_id:
        carrier_row = await db.execute(
            select(Carrier).where(
                Carrier.id == str(body.carrier_id),
                Carrier.tenant_id == user.tenant_id,
            )
        )
        if not carrier_row.scalar_one_or_none():
            raise NotFoundError("Carrier", str(body.carrier_id))

    shipment = Shipment(
        tenant_id=str(user.tenant_id),
        carrier_id=str(body.carrier_id) if body.carrier_id else None,
        origin=body.origin,
        destination=body.destination,
        sector=body.sector,
        mode=body.mode,
        weight_kg=body.weight_kg,
        volume_m3=body.volume_m3,
        temperature_c=body.temperature_c,
        estimated_delivery=body.estimated_delivery,
    )
    db.add(shipment)
    await db.commit()
    await db.refresh(shipment)

    # Fire-and-forget usage event
    await record_event(str(user.tenant_id), "shipment_created")

    log.info("shipment.created", shipment_id=str(shipment.id), tenant_id=str(user.tenant_id))
    return shipment


@router.get("/{shipment_id}", response_model=ShipmentRead)
async def get_shipment(
    shipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Shipment:
    """Fetch a single shipment by ID."""
    row = (
        await db.execute(select(Shipment).where(Shipment.id == str(shipment_id)))
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError("Shipment", str(shipment_id))
    _assert_tenant(row.tenant_id, user)
    return row


@router.patch("/{shipment_id}", response_model=ShipmentRead)
async def update_shipment(
    shipment_id: UUID,
    body: ShipmentUpdate,
    user: User = Depends(require_role(UserRole.OPERATOR)),
    db: AsyncSession = Depends(get_db_session),
) -> Shipment:
    """Partially update shipment status, mode, or delivery dates."""
    row = (
        await db.execute(select(Shipment).where(Shipment.id == str(shipment_id)))
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError("Shipment", str(shipment_id))
    _assert_tenant(row.tenant_id, user)

    # Prevent re-opening a cancelled shipment
    if (
        row.status == ShipmentStatus.CANCELLED
        and body.status
        and body.status != ShipmentStatus.CANCELLED
    ):
        raise ValidationError("Cannot reopen a cancelled shipment", field="status")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    log.info("shipment.updated", shipment_id=str(shipment_id), changes=list(update_data.keys()))
    return row


@router.delete("/{shipment_id}", status_code=204)
async def cancel_shipment(
    shipment_id: UUID,
    user: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete a shipment by setting its status to CANCELLED."""
    row = (
        await db.execute(select(Shipment).where(Shipment.id == str(shipment_id)))
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError("Shipment", str(shipment_id))
    _assert_tenant(row.tenant_id, user)

    if row.status == ShipmentStatus.DELIVERED:
        raise ValidationError("Cannot cancel a delivered shipment", field="status")

    row.status = ShipmentStatus.CANCELLED
    await db.commit()
    log.info("shipment.cancelled", shipment_id=str(shipment_id), user_id=str(user.id))


# ─────────────────────────────────────────────────────────────
# Carrier routes
# ─────────────────────────────────────────────────────────────


@carrier_router.get("", response_model=list[CarrierRead])
async def list_carriers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[Carrier]:
    rows = (
        (
            await db.execute(
                select(Carrier).where(Carrier.tenant_id == user.tenant_id).order_by(Carrier.name)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@carrier_router.post("", response_model=CarrierRead, status_code=201)
async def create_carrier(
    body: CarrierCreate,
    user: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> Carrier:
    # Uniqueness check within tenant
    existing = (
        await db.execute(
            select(Carrier).where(Carrier.tenant_id == user.tenant_id, Carrier.name == body.name)
        )
    ).scalar_one_or_none()
    if existing:
        raise ConflictError(f"Carrier '{body.name}' already exists for this tenant")

    carrier = Carrier(tenant_id=str(user.tenant_id), name=body.name)
    db.add(carrier)
    await db.commit()
    await db.refresh(carrier)
    log.info("carrier.created", carrier_id=str(carrier.id), name=carrier.name)
    return carrier


@carrier_router.get("/{carrier_id}", response_model=CarrierRead)
async def get_carrier(
    carrier_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Carrier:
    row = (
        await db.execute(select(Carrier).where(Carrier.id == str(carrier_id)))
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError("Carrier", str(carrier_id))
    _assert_tenant(row.tenant_id, user)
    return row

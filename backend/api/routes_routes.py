"""
api/routes_routes.py — Route segment management endpoints.

Endpoints:
  GET  /routes             — list route segments for the tenant (paginated)
  GET  /routes/{id}        — single segment detail
  GET  /routes/geojson     — all segments as GeoJSON FeatureCollection for map rendering
  POST /routes/simulate    — demo: broadcast a mock disruption event over WebSocket

Follows the same patterns as shipment_routes.py:
  - Tenant isolation via RLS (get_db_session already sets app.tenant_id)
  - Pagination via offset/limit
  - LogistiQError subclasses only (no direct HTTPException)
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.exceptions import NotFoundError
from core.schemas import PaginatedResponse
from db.database import get_db_session
from db.models import RouteSegment, User

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/routes", tags=["routes"])


# ─────────────────────────────────────────────────────────────
# GET /routes
# ─────────────────────────────────────────────────────────────


@router.get("", response_model=PaginatedResponse[dict[str, Any]])
async def list_route_segments(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    highway_code: str | None = Query(None, description="Filter by highway code"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[dict[str, Any]]:
    """List route segments accessible to this tenant (paginated)."""
    base_q = select(RouteSegment).where(
        (RouteSegment.tenant_id == current_user.tenant_id)
        | RouteSegment.tenant_id.is_(None)  # global segments visible to all
    )
    if highway_code:
        base_q = base_q.where(RouteSegment.highway_code == highway_code)

    # Total count
    count_q = select(func.count()).select_from(base_q.subquery())
    total: int = (await db.execute(count_q)).scalar_one()

    # Paginated rows
    rows = (await db.execute(base_q.offset(offset).limit(limit))).scalars().all()

    items = [
        {
            "id": str(r.id),
            "tenant_id": str(r.tenant_id) if r.tenant_id else None,
            "highway_code": r.highway_code,
            "risk_score": r.risk_score,
            "elevation_avg_m": r.elevation_avg_m,
            "flood_prob": r.flood_prob,
            "fire_risk": r.fire_risk,
            "congestion_idx": r.congestion_idx,
            "last_scored_at": r.last_scored_at.isoformat() if r.last_scored_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

    log.info("routes.list", tenant_id=current_user.tenant_id, total=total, offset=offset)
    return PaginatedResponse(total=total, offset=offset, limit=limit, items=items)


# ─────────────────────────────────────────────────────────────
# GET /routes/geojson  (must be before /{segment_id} to avoid routing conflict)
# ─────────────────────────────────────────────────────────────


@router.get("/geojson", response_model=dict[str, Any])
async def route_segments_geojson(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return all route segments as a GeoJSON FeatureCollection.

    Uses PostGIS ST_AsGeoJSON to serialise geometry efficiently server-side.
    Suitable for direct consumption by MapLibre / deck.gl.
    """
    sql = text("""
        SELECT
            rs.id::text,
            rs.highway_code,
            rs.risk_score,
            rs.flood_prob,
            rs.fire_risk,
            rs.congestion_idx,
            ST_AsGeoJSON(rs.geom)::json AS geometry
        FROM route_segments rs
        WHERE
            rs.geom IS NOT NULL
            AND (rs.tenant_id = :tenant_id OR rs.tenant_id IS NULL)
        LIMIT 5000
    """)

    result = await db.execute(sql, {"tenant_id": str(current_user.tenant_id)})
    rows = result.mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "id": row["id"],
                "highway_code": row["highway_code"],
                "risk_score": row["risk_score"],
                "flood_prob": row["flood_prob"],
                "fire_risk": row["fire_risk"],
                "congestion_idx": row["congestion_idx"],
            },
        }
        for row in rows
        if row["geometry"] is not None
    ]

    log.info("routes.geojson", tenant_id=current_user.tenant_id, features=len(features))
    return {"type": "FeatureCollection", "features": features}


# ─────────────────────────────────────────────────────────────
# GET /routes/{segment_id}
# ─────────────────────────────────────────────────────────────


@router.get("/{segment_id}", response_model=dict[str, Any])
async def get_route_segment(
    segment_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch a single route segment by ID."""
    row = (
        await db.execute(
            select(RouteSegment).where(
                RouteSegment.id == segment_id,
                (RouteSegment.tenant_id == current_user.tenant_id)
                | RouteSegment.tenant_id.is_(None),
            )
        )
    ).scalar_one_or_none()

    if not row:
        raise NotFoundError("RouteSegment", segment_id)

    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "highway_code": row.highway_code,
        "risk_score": row.risk_score,
        "elevation_avg_m": row.elevation_avg_m,
        "flood_prob": row.flood_prob,
        "fire_risk": row.fire_risk,
        "congestion_idx": row.congestion_idx,
        "last_scored_at": row.last_scored_at.isoformat() if row.last_scored_at else None,
        "created_at": row.created_at.isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# POST /routes/simulate-disruption
# ─────────────────────────────────────────────────────────────


@router.post("/simulate-disruption", response_model=dict[str, Any])
async def simulate_disruption(
    segment_id: str | None = None,
    disruption_type: str = "flood",
    risk_score: float = Query(0.85, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Demo endpoint: broadcast a mock disruption event over WebSocket.

    Useful for front-end development and demo without requiring the
    sentinel scheduler to be running.
    """
    from datetime import datetime

    from api.websocket_routes import manager  # noqa: E402

    payload = {
        "type": "new_disruption",
        "disruption_type": disruption_type,
        "risk_score": risk_score,
        "segment_id": segment_id,
        "simulated": True,
        "ts": datetime.now(UTC).isoformat(),
    }

    tenant_id = str(current_user.tenant_id)
    await manager.broadcast(f"tenant:{tenant_id}:disruptions", payload)
    await manager.broadcast(
        f"tenant:{tenant_id}:dashboard",
        {
            "type": "tick",
            "connections": manager.connection_count(),
            "ts": datetime.now(UTC).isoformat(),
        },
    )

    log.info(
        "routes.simulate_disruption",
        tenant_id=tenant_id,
        disruption_type=disruption_type,
        risk_score=risk_score,
    )
    return {"status": "broadcast_sent", "tenant_id": tenant_id, "payload": payload}

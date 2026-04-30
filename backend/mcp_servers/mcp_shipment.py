"""
MCP Shipment Server — shipment CRUD, status updates, telemetry, analytics.

All database access goes through SQLAlchemy async sessions.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from db.models import Shipment
from mcp_servers.base import MCPServer, MCPToolSchema

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Async DB session factory (isolated from the request context)
# ─────────────────────────────────────────────────────────────

_engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True, pool_pre_ping=True)
_SessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def _get_session() -> AsyncSession:
    return _SessionLocal()


# ─────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────


class ShipmentSummary(BaseModel):
    id: str
    tenant_id: str
    status: str
    origin: str
    destination: str
    mode: str
    sector: str
    carrier_id: str | None = None


class ShipmentStatusUpdate(BaseModel):
    shipment_id: str
    new_status: str
    updated_by: str | None = None


class ShipmentAnalytics(BaseModel):
    tenant_id: str
    total: int
    by_status: dict[str, int]
    by_mode: dict[str, int]
    on_time_rate: float


# ─────────────────────────────────────────────────────────────
# MCP Shipment Server
# ─────────────────────────────────────────────────────────────


class ShipmentMCPServer(MCPServer):
    tools: dict[str, MCPToolSchema] = {
        "list_shipments": MCPToolSchema(
            name="list_shipments",
            description="Return a paginated list of shipments for the current tenant.",
            parameters={
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "in_transit",
                            "delivered",
                            "delayed",
                            "cancelled",
                            "all",
                        ],
                        "default": "all",
                    },
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                },
            },
            required=[],
        ),
        "get_shipment": MCPToolSchema(
            name="get_shipment",
            description="Fetch a single shipment by ID.",
            parameters={
                "type": "object",
                "properties": {
                    "shipment_id": {"type": "string"},
                },
            },
            required=["shipment_id"],
        ),
        "update_shipment_status": MCPToolSchema(
            name="update_shipment_status",
            description="Update the status of a shipment.",
            parameters={
                "type": "object",
                "properties": {
                    "shipment_id": {"type": "string"},
                    "new_status": {
                        "type": "string",
                        "enum": ["pending", "in_transit", "delivered", "delayed", "cancelled"],
                    },
                    "updated_by": {"type": "string"},
                },
            },
            required=["shipment_id", "new_status"],
        ),
        "get_shipment_analytics": MCPToolSchema(
            name="get_shipment_analytics",
            description="Return aggregate analytics for the tenant's shipments.",
            parameters={"type": "object", "properties": {}},
            required=[],
        ),
        "search_shipments": MCPToolSchema(
            name="search_shipments",
            description="Full-text search shipments by origin, destination, or carrier.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
            required=["query"],
        ),
    }

    async def execute_tool(self, name: str, params: dict[str, Any], tenant_id: str | None) -> Any:
        match name:
            case "list_shipments":
                return await self._list_shipments(
                    tenant_id,
                    params.get("status_filter", "all"),
                    params.get("limit", 50),
                    params.get("offset", 0),
                )
            case "get_shipment":
                return await self._get_shipment(params["shipment_id"], tenant_id)
            case "update_shipment_status":
                return await self._update_status(
                    params["shipment_id"],
                    params["new_status"],
                    params.get("updated_by"),
                    tenant_id,
                )
            case "get_shipment_analytics":
                return (await self._get_analytics(tenant_id)).model_dump()
            case "search_shipments":
                return await self._search(params["query"], tenant_id, params.get("limit", 20))
            case _:
                raise ValueError(f"Unknown tool: {name}")

    # ── Implementations ───────────────────────────────────────

    async def _list_shipments(
        self,
        tenant_id: str | None,
        status_filter: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        async with _SessionLocal() as session:
            if tenant_id:
                await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})

            stmt = select(Shipment).limit(limit).offset(offset)
            if status_filter != "all":
                stmt = stmt.where(Shipment.status == status_filter)

            rows = (await session.execute(stmt)).scalars().all()

        return [
            {
                "id": str(s.id),
                "tenant_id": str(s.tenant_id),
                "status": s.status.value if hasattr(s.status, "value") else s.status,
                "origin": s.origin,
                "destination": s.destination,
                "mode": s.mode.value if hasattr(s.mode, "value") else s.mode,
                "sector": s.sector,
                "carrier_id": str(s.carrier_id) if s.carrier_id else None,
            }
            for s in rows
        ]

    async def _get_shipment(self, shipment_id: str, tenant_id: str | None) -> dict[str, Any]:
        async with _SessionLocal() as session:
            if tenant_id:
                await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})
            row = (
                await session.execute(select(Shipment).where(Shipment.id == shipment_id))
            ).scalar_one_or_none()

        if not row:
            raise ValueError(f"Shipment {shipment_id!r} not found")

        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "status": row.status.value if hasattr(row.status, "value") else row.status,
            "origin": row.origin,
            "destination": row.destination,
            "mode": row.mode.value if hasattr(row.mode, "value") else row.mode,
            "sector": row.sector,
            "weight_kg": row.weight_kg,
            "volume_m3": row.volume_m3,
            "estimated_delivery": str(row.estimated_delivery) if row.estimated_delivery else None,
            "actual_delivery": str(row.actual_delivery) if row.actual_delivery else None,
        }

    async def _update_status(
        self,
        shipment_id: str,
        new_status: str,
        updated_by: str | None,
        tenant_id: str | None,
    ) -> dict[str, Any]:
        async with _SessionLocal() as session:
            if tenant_id:
                await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})
            await session.execute(
                update(Shipment).where(Shipment.id == shipment_id).values(status=new_status)
            )
            await session.commit()

        log.info(
            "shipment.status_updated",
            shipment_id=shipment_id,
            new_status=new_status,
            updated_by=updated_by,
            tenant_id=tenant_id,
        )
        return {"shipment_id": shipment_id, "new_status": new_status, "success": True}

    async def _get_analytics(self, tenant_id: str | None) -> ShipmentAnalytics:
        async with _SessionLocal() as session:
            if tenant_id:
                await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})
            rows = (await session.execute(select(Shipment))).scalars().all()

        total = len(rows)
        by_status: dict[str, int] = {}
        by_mode: dict[str, int] = {}
        delivered = 0

        for s in rows:
            st = s.status.value if hasattr(s.status, "value") else str(s.status)
            md = s.mode.value if hasattr(s.mode, "value") else str(s.mode)
            by_status[st] = by_status.get(st, 0) + 1
            by_mode[md] = by_mode.get(md, 0) + 1
            if st == "delivered":
                delivered += 1

        on_time_rate = round(delivered / total, 4) if total else 0.0
        return ShipmentAnalytics(
            tenant_id=str(tenant_id) if tenant_id else "unknown",
            total=total,
            by_status=by_status,
            by_mode=by_mode,
            on_time_rate=on_time_rate,
        )

    async def _search(self, query: str, tenant_id: str | None, limit: int) -> list[dict[str, Any]]:
        async with _SessionLocal() as session:
            if tenant_id:
                await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})
            stmt = (
                select(Shipment)
                .where(
                    (Shipment.origin.ilike(f"%{query}%"))
                    | (Shipment.destination.ilike(f"%{query}%"))
                    | (Shipment.sector.ilike(f"%{query}%"))
                )
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()

        return [
            {
                "id": str(s.id),
                "origin": s.origin,
                "destination": s.destination,
                "status": s.status.value if hasattr(s.status, "value") else s.status,
                "sector": s.sector,
            }
            for s in rows
        ]


# Singleton instance
shipment_mcp = ShipmentMCPServer(prefix="/mcp/shipment")

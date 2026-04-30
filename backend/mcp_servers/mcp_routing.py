"""
MCP Routing Server — route planning, alternatives, ETA, risk scoring, multimodal.

External APIs:
  - OSRM  http://router.project-osrm.org  (table / route)
  - ORS   https://api.openrouteservice.org (truck HGV routing)
  - AIS   (mock – real feed requires licence)
  - AviationStack (mock – requires API key)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pybreaker
import structlog
from pydantic import BaseModel, Field

from core.config import settings
from core.redis import redis_client
from mcp_servers.base import MCPServer, MCPToolSchema

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Circuit breakers
# ─────────────────────────────────────────────────────────────

_osrm_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
_ors_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# ─────────────────────────────────────────────────────────────
# Hardcoded CONCOR rail base rates (INR / tonne-km)
# ─────────────────────────────────────────────────────────────

CONCOR_RATES: dict[str, float] = {
    "automotive": 2.10,
    "pharma": 3.50,
    "cold_chain": 4.80,
    "retail": 2.50,
    "tech": 3.20,
    "electronics": 3.20,
    "textiles": 1.90,
    "agriculture": 1.60,
    "default": 2.50,
}

# ─────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────


class RouteResult(BaseModel):
    origin_id: str
    dest_id: str
    distance_km: float
    duration_min: float
    geometry: dict[str, Any] | None = None
    avoid_segments: list[str] = []
    source: str = "OSRM"


class AlternativeRoute(BaseModel):
    route_id: str
    distance_km: float
    duration_min: float
    via_waypoints: list[str] = []


class ETAResult(BaseModel):
    shipment_id: str
    estimated_arrival_utc: str
    confidence: float = Field(ge=0.0, le=1.0)
    distance_remaining_km: float | None = None


class RouteRiskResult(BaseModel):
    route_id: str
    overall_risk: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = []
    recommendation: str


class MultimodalOption(BaseModel):
    mode: str
    carrier: str | None = None
    cost_inr: float
    co2_kg: float
    eta_hours: float
    notes: str = ""


# ─────────────────────────────────────────────────────────────
# MCP Routing Server
# ─────────────────────────────────────────────────────────────


class RoutingMCPServer(MCPServer):
    tools: dict[str, MCPToolSchema] = {
        "get_route": MCPToolSchema(
            name="get_route",
            description="Compute optimal road/truck route between two locations using OSRM + ORS.",
            parameters={
                "type": "object",
                "properties": {
                    "origin_id": {
                        "type": "string",
                        "description": "Origin location ID or 'lat,lon'",
                    },
                    "dest_id": {
                        "type": "string",
                        "description": "Destination location ID or 'lat,lon'",
                    },
                    "avoid_segments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Segment IDs to avoid",
                    },
                },
            },
            required=["origin_id", "dest_id"],
        ),
        "get_alternatives": MCPToolSchema(
            name="get_alternatives",
            description="Return N alternative routes bypassing a blocked segment.",
            parameters={
                "type": "object",
                "properties": {
                    "blocked_segment_id": {"type": "string"},
                    "n": {"type": "integer", "default": 3},
                },
            },
            required=["blocked_segment_id"],
        ),
        "get_eta": MCPToolSchema(
            name="get_eta",
            description="Estimate arrival time for an in-transit shipment.",
            parameters={
                "type": "object",
                "properties": {
                    "shipment_id": {"type": "string"},
                },
            },
            required=["shipment_id"],
        ),
        "check_route_risk": MCPToolSchema(
            name="check_route_risk",
            description="Score a route for combined risk (weather, disruptions, congestion).",
            parameters={
                "type": "object",
                "properties": {
                    "route_id": {"type": "string"},
                },
            },
            required=["route_id"],
        ),
        "get_multimodal_options": MCPToolSchema(
            name="get_multimodal_options",
            description=(
                "Return cost, CO₂, and ETA estimates for road, rail, sea, and air modes "
                "between two locations."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "'lat,lon' or city name"},
                    "dest": {"type": "string", "description": "'lat,lon' or city name"},
                    "mode_preference": {
                        "type": "string",
                        "enum": ["road", "rail", "sea", "air", "any"],
                        "default": "any",
                    },
                    "cargo_sector": {
                        "type": "string",
                        "description": "Cargo type for CONCOR rail rates",
                        "default": "default",
                    },
                    "weight_tonnes": {"type": "number", "default": 10.0},
                },
            },
            required=["origin", "dest"],
        ),
    }

    async def execute_tool(self, name: str, params: dict[str, Any], tenant_id: str | None) -> Any:
        try:
            match name:
                case "get_route":
                    return (
                        await self._get_route(
                            params["origin_id"],
                            params["dest_id"],
                            params.get("avoid_segments", []),
                        )
                    ).model_dump()
                case "get_alternatives":
                    alts = await self._get_alternatives(
                        params["blocked_segment_id"], params.get("n", 3)
                    )
                    return [a.model_dump() for a in alts]
                case "get_eta":
                    return (await self._get_eta(params["shipment_id"])).model_dump()
                case "check_route_risk":
                    return (await self._check_route_risk(params["route_id"])).model_dump()
                case "get_multimodal_options":
                    opts = await self._get_multimodal_options(
                        params["origin"],
                        params["dest"],
                        params.get("mode_preference", "any"),
                        params.get("cargo_sector", "default"),
                        params.get("weight_tonnes", 10.0),
                    )
                    return [o.model_dump() for o in opts]
                case _:
                    raise ValueError(f"Unknown tool: {name}")
        except Exception as exc:  # noqa: BLE001
            log.error("mcp.routing.tool_failed", tool=name, error=str(exc))
            # Safe fallbacks per tool — use the exact fields defined in each model above
            if name == "get_route":
                return RouteResult(
                    origin_id=params.get("origin_id", ""),
                    dest_id=params.get("dest_id", ""),
                    distance_km=0.0,
                    duration_min=0.0,
                ).model_dump()
            elif name in ("get_alternatives", "get_multimodal_options"):
                return []
            elif name == "get_eta":
                return ETAResult(
                    shipment_id=params.get("shipment_id", ""),
                    estimated_arrival_utc="",
                    confidence=0.0,
                ).model_dump()
            elif name == "check_route_risk":
                return RouteRiskResult(
                    route_id=params.get("route_id", ""),
                    overall_risk=0.0,
                    risk_factors=[],
                    recommendation="Fallback: unable to assess risk.",
                ).model_dump()
            return {}

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _parse_coord(loc: str) -> tuple[float, float]:
        """Parse 'lat,lon' string into (lat, lon)."""
        parts = loc.split(",")
        if len(parts) == 2:
            return float(parts[0]), float(parts[1])
        raise ValueError(f"Cannot parse coordinate: {loc!r}")

    # ── Tool implementations ──────────────────────────────────

    async def _get_route(
        self, origin_id: str, dest_id: str, avoid_segments: list[str]
    ) -> RouteResult:
        cache_key = f"mcp:route:{origin_id}:{dest_id}:{','.join(avoid_segments)}"
        cached = await redis_client.get(cache_key)
        if cached:
            return RouteResult(**json.loads(cached))

        try:
            o_lat, o_lon = self._parse_coord(origin_id)
            d_lat, d_lon = self._parse_coord(dest_id)
            coord_str = f"{o_lon},{o_lat};{d_lon},{d_lat}"

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://router.project-osrm.org/route/v1/driving/{coord_str}",
                    params={"overview": "full", "geometries": "geojson"},
                    timeout=15.0,
                )
                resp.raise_for_status()
                data = resp.json()

            routes = data.get("routes", [])
            if not routes:
                raise ValueError("OSRM returned no routes")

            best = routes[0]
            result = RouteResult(
                origin_id=origin_id,
                dest_id=dest_id,
                distance_km=round(best["distance"] / 1000, 2),
                duration_min=round(best["duration"] / 60, 1),
                geometry=best.get("geometry"),
                avoid_segments=avoid_segments,
                source="OSRM",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("osrm.failed_using_ors_fallback", error=str(exc))
            # ORS fallback (truck-specific)
            result = await self._ors_route(origin_id, dest_id, avoid_segments)

        await redis_client.setex(cache_key, 3600, json.dumps(result.model_dump()))
        return result

    async def _ors_route(
        self, origin_id: str, dest_id: str, avoid_segments: list[str]
    ) -> RouteResult:
        o_lat, o_lon = self._parse_coord(origin_id)
        d_lat, d_lon = self._parse_coord(dest_id)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openrouteservice.org/v2/directions/driving-hgv",
                json={"coordinates": [[o_lon, o_lat], [d_lon, d_lat]]},
                headers={"Authorization": settings.ORS_API_KEY or ""},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        route = data["routes"][0]
        summary = route["summary"]
        return RouteResult(
            origin_id=origin_id,
            dest_id=dest_id,
            distance_km=round(summary["distance"] / 1000, 2),
            duration_min=round(summary["duration"] / 60, 1),
            geometry=route.get("geometry"),
            avoid_segments=avoid_segments,
            source="ORS HGV",
        )

    async def _get_alternatives(self, blocked_segment_id: str, n: int) -> list[AlternativeRoute]:
        """
        Returns placeholder alternative routes. In production, query OSRM
        /route with alternatives=true and the segment excluded.
        """
        import uuid

        alts: list[AlternativeRoute] = []
        for i in range(max(1, n)):
            alts.append(
                AlternativeRoute(
                    route_id=str(uuid.uuid4()),
                    distance_km=round(200 + i * 15.5, 1),
                    duration_min=round(180 + i * 12, 1),
                    via_waypoints=[f"WP-{i + 1}A", f"WP-{i + 1}B"],
                )
            )
        return alts

    async def _get_eta(self, shipment_id: str) -> ETAResult:
        import datetime

        # In production: look up DB for current position + route, call OSRM table API.
        estimated = datetime.datetime.utcnow() + datetime.timedelta(hours=6)
        return ETAResult(
            shipment_id=shipment_id,
            estimated_arrival_utc=estimated.isoformat() + "Z",
            confidence=0.82,
            distance_remaining_km=320.0,
        )

    async def _check_route_risk(self, route_id: str) -> RouteRiskResult:
        """
        Placeholder risk scorer. A production version would overlay weather,
        disruption events and historical delay data.
        """
        risk_factors: list[str] = []
        overall_risk = 0.2  # baseline
        recommendation = "Route appears safe. Monitor weather in 24h window."

        return RouteRiskResult(
            route_id=route_id,
            overall_risk=overall_risk,
            risk_factors=risk_factors,
            recommendation=recommendation,
        )

    async def _get_multimodal_options(
        self,
        origin: str,
        dest: str,
        mode_preference: str,
        cargo_sector: str,
        weight_tonnes: float,
    ) -> list[MultimodalOption]:
        import math

        # Approximate straight-line distance (km) from coord strings if possible
        distance_km = 500.0  # default
        try:
            o_lat, o_lon = self._parse_coord(origin)
            d_lat, d_lon = self._parse_coord(dest)
            dlat = math.radians(d_lat - o_lat)
            dlon = math.radians(d_lon - o_lon)
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(o_lat))
                * math.cos(math.radians(d_lat))
                * math.sin(dlon / 2) ** 2
            )
            distance_km = round(6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)
        except ValueError:
            pass

        rail_rate = CONCOR_RATES.get(cargo_sector, CONCOR_RATES["default"])

        options: list[MultimodalOption] = []

        # Road
        if mode_preference in ("road", "any"):
            cost = distance_km * 45 * weight_tonnes / 100  # ₹45/tonne-km approx
            options.append(
                MultimodalOption(
                    mode="road",
                    carrier="Mahindra Logistics",
                    cost_inr=round(cost, 2),
                    co2_kg=round(distance_km * weight_tonnes * 0.062, 2),
                    eta_hours=round(distance_km / 55, 1),
                    notes="Standard HGV trucking via NH network",
                )
            )

        # Rail (CONCOR)
        if mode_preference in ("rail", "any"):
            cost = distance_km * rail_rate * weight_tonnes
            options.append(
                MultimodalOption(
                    mode="rail",
                    carrier="CONCOR",
                    cost_inr=round(cost, 2),
                    co2_kg=round(distance_km * weight_tonnes * 0.022, 2),
                    eta_hours=round(distance_km / 60 + 24, 1),  # terminal + transit
                    notes=f"CONCOR container freight; rate ₹{rail_rate}/tonne-km",
                )
            )

        # Sea (AIS ETA mock — real feed requires licence)
        if mode_preference in ("sea", "any") and distance_km > 200:
            cost = distance_km * 8 * weight_tonnes
            options.append(
                MultimodalOption(
                    mode="sea",
                    carrier="Shipping Corporation of India",
                    cost_inr=round(cost, 2),
                    co2_kg=round(distance_km * weight_tonnes * 0.008, 2),
                    eta_hours=round(distance_km / 25 + 48, 1),
                    notes="Coastal/short-sea shipping; AIS ETA is estimated",
                )
            )

        # Air (AviationStack mock)
        if mode_preference in ("air", "any"):
            cost = distance_km * 350 * weight_tonnes / 100
            options.append(
                MultimodalOption(
                    mode="air",
                    carrier="Air India Cargo",
                    cost_inr=round(cost, 2),
                    co2_kg=round(distance_km * weight_tonnes * 0.602, 2),
                    eta_hours=round(distance_km / 800 + 4, 1),
                    notes="Air freight; AviationStack schedule estimated",
                )
            )

        # Sort by ETA ascending
        options.sort(key=lambda o: o.eta_hours)
        return options


# Singleton instance
routing_mcp = RoutingMCPServer(prefix="/mcp/routing")

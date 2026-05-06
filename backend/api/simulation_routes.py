"""
api/simulation_routes.py — Realtime shipment simulation endpoints for dashboard demos.

Endpoint:
  POST /simulation/demo

Behavior:
  - Picks 9 tenant shipments (3 road, 3 air, 3 sea)
  - Resets risk to 0 and marks IN_TRANSIT
  - Launches a background async worker that updates coordinates every tick
  - Publishes live updates to Redis channel: shipments:{tenant_id}
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.config import settings
from core.exceptions import ValidationError
from core.redis import redis_client
from db.database import AsyncSessionLocal, get_db_session
from db.models import Shipment, ShipmentMode, ShipmentStatus, User, UserRole

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/simulation", tags=["simulation"])


DEMO_MODE_SEQUENCE: list[ShipmentMode] = [
    ShipmentMode.ROAD,
    ShipmentMode.AIR,
    ShipmentMode.SEA,
]

MODE_SPEEDS_KMH: dict[ShipmentMode, float] = {
    ShipmentMode.ROAD: 60.0,
    ShipmentMode.SEA: 40.0,
    ShipmentMode.AIR: 800.0,
}

DEMO_CITY_PAIRS: list[tuple[str, str]] = [
    ("Mumbai", "Delhi"),
    ("Bangalore", "Chennai"),
    ("Kolkata", "Patna"),
    ("Hyderabad", "Pune"),
    ("Ahmedabad", "Jaipur"),
    ("Surat", "Nagpur"),
    ("Lucknow", "Kanpur"),
    ("Bhopal", "Visakhapatnam"),
    ("Vadodara", "Thane"),
]

_DEMO_SEED_PAIRS: list[tuple[str, str, ShipmentMode]] = [
    # Road (3 shipments)
    ("Mumbai", "Delhi", ShipmentMode.ROAD),
    ("Pune", "Nagpur", ShipmentMode.ROAD),
    ("Ahmedabad", "Jaipur", ShipmentMode.ROAD),
    # Air (3 shipments)
    ("Bangalore", "Kolkata", ShipmentMode.AIR),
    ("Chennai", "Lucknow", ShipmentMode.AIR),
    ("Hyderabad", "Delhi", ShipmentMode.AIR),
    # Sea (3 shipments)
    ("Mumbai", "Chennai", ShipmentMode.SEA),
    ("Kolkata", "Mumbai", ShipmentMode.SEA),
    ("Surat", "Visakhapatnam", ShipmentMode.SEA),
]

INDIAN_CITY_COORDS: dict[str, tuple[float, float]] = {
    "mumbai": (72.8777, 19.0760),
    "delhi": (77.1025, 28.7041),
    "new delhi": (77.1025, 28.7041),
    "bangalore": (77.5858, 12.9716),
    "bengaluru": (77.5858, 12.9716),
    "hyderabad": (78.4867, 17.3850),
    "chennai": (80.2707, 13.0827),
    "kolkata": (88.3639, 22.5726),
    "ahmedabad": (72.5713, 23.0225),
    "pune": (73.8567, 18.5204),
    "surat": (72.8777, 21.1702),
    "jaipur": (75.7139, 26.9124),
    "lucknow": (80.9462, 26.8467),
    "kanpur": (80.3318, 26.4499),
    "nagpur": (79.0882, 21.1458),
    "indore": (75.8577, 22.7196),
    "thane": (72.9780, 19.2183),
    "bhopal": (77.4120, 23.2599),
    "visakhapatnam": (83.2185, 17.6868),
    "pimpri-chinchwad": (73.7949, 18.6332),
    "patna": (85.1376, 25.5941),
    "vadodara": (73.1812, 22.3072),
}

_simulation_tasks: dict[str, asyncio.Task[None]] = {}
_active_simulations: dict[str, list[SimulatedShipment]] = {}
_simulation_lock = asyncio.Lock()
_simulation_speed: dict[str, float] = {}  # live-updated without restart
_active_fire: dict[str, dict] = {}         # keyed by tenant_id while fire is active

# ── Fire simulation constants (shared between trigger + worker) ──────────────
_FIRE_BYPASS_KM: float = 40.0   # green route diverges this far before the fire
_FIRE_STOP_BUFFER: float = 0.02  # progress units (~5 km) truck stops before decision pt


async def _fire_vrp_background_task(
    tenant_id: str,
    shipment_id: str,
    event_id: str,
    disruption_desc: str,
    disruption_event: dict,
    r_lon: float, r_lat: float,   # decision point (green route origin)
    d_lon: float, d_lat: float,   # destination
    fire_lat: float, fire_lon: float,
    decision_progress: float,
    fire_progress: float,
    decision_lon: float, decision_lat: float,
    origin: str, destination: str,
) -> None:
    """Background task: compute OSRM alternate routes and publish VRP + agent results.
    Runs AFTER the fire endpoint has already returned so trucks never freeze.
    """
    import numpy as np
    from ml.vrp_solver import VRPInput, VRPNode, VRPVehicle, solve

    # Perpendicular detour: shift fire location sideways ~55 km
    # This ensures the alternate route bypasses the fire effectively,
    # rather than continuing on the highway past the fire.
    dx = d_lon - r_lon
    dy = d_lat - r_lat
    length = (dx**2 + dy**2) ** 0.5
    px, py = (-dy / length, dx / length) if length > 0 else (0.0, 0.0)
    
    i_lon = max(68.5, min(97.0, fire_lon + px * 0.5))
    i_lat = max(8.5,  min(37.0, fire_lat + py * 0.5))

    alternate_routes: list[dict[str, Any]] = []
    try:
        nodes = [
            VRPNode(id="current",  lat=r_lat, lon=r_lon, demand_kg=0),
            VRPNode(id="detour",   lat=i_lat, lon=i_lon, demand_kg=100),
            VRPNode(id="dest",     lat=d_lat, lon=d_lon, demand_kg=0),
        ]
        vrp_input = VRPInput(
            nodes=nodes,
            vehicles=[VRPVehicle(id="v1", capacity_kg=5000, depot_node_id="current", mode="road")],
            risk_matrix=np.zeros((3, 3)),
        )
        vrp_solution = await asyncio.to_thread(solve, vrp_input)
        leg1 = await _fetch_osrm_route(r_lon, r_lat, i_lon, i_lat)
        leg2 = await _fetch_osrm_route(i_lon, i_lat, d_lon, d_lat)
        full_geom = leg1 + leg2[1:] if leg2 else leg1
        alternate_routes.append({
            "route_id":    f"{event_id}-alt-0",
            "distance_km": vrp_solution.total_km,
            "duration_min": round(vrp_solution.total_km / 60 * 60, 0),
            "via_waypoints": ["VRP Computed Detour"],
            "cost_inr":    vrp_solution.total_cost_inr,
            "eta_hours":   round(vrp_solution.total_km / 60, 1),
            "geometry":    full_geom if full_geom else [],
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("fire.vrp_bg.failed", error=str(exc))

    if not alternate_routes:
        await redis_client.publish(
            f"shipments:{tenant_id}",
            json.dumps({
                "type": "vrp_error",
                "message": "⚠️ Alternate route unavailable — OSRM offline. Fire marker active.",
                "shipment_id": shipment_id,
            }),
        )
        return

    vrp_payload = {
        "trace_id":   f"vrp-fast-{event_id}",
        "timestamp":  _utc_now(),
        "disruption": {
            "description":       disruption_desc,
            "severity":          "critical",
            "event_type":        "fire",
            "lat":               fire_lat,
            "lon":               fire_lon,
            "shipment_id":       shipment_id,
            "truck_progress":    round(decision_progress, 6),
            "fire_progress":     round(fire_progress, 6),
            "decision_progress": round(decision_progress, 6),
            "decision_lon":      decision_lon,
            "decision_lat":      decision_lat,
        },
        "alternate_routes":   {shipment_id: alternate_routes},
        "selected_actions":   ["reroute_initiated", "carrier_notified"],
        "fallback_used":      False,
        "source":             "OSRM_FAST",
        "gemini_tokens_used": 0,
        "total_cost_delta_inr": alternate_routes[0].get("cost_inr", 0),
    }
    vrp_json = json.dumps(vrp_payload)
    await redis_client.publish(f"vrp_results:{tenant_id}", vrp_json)
    await redis_client.setex(f"vrp_results:{tenant_id}:latest", 3600, vrp_json)

    # Publish to disruptions for Gemini Decision Agent
    await redis_client.publish("disruptions", json.dumps(disruption_event))

    # Agent log preview
    agent_preview = {
        "trace_id":  f"fire-preview-{uuid.uuid4().hex[:6]}",
        "timestamp": _utc_now(),
        "disruption": {
            "description": disruption_desc,
            "severity": "critical",
            "event_type": "fire",
            "shipment_id": shipment_id,
        },
        "description": disruption_desc,
        "severity":    "critical",
        "actions":     ["alert_dispatched", "reroute_initiated"],
        "message":     f"🔥 Fire on {origin}→{destination}. {len(alternate_routes)} alternate route(s) computed.",
        "human_escalated": False,
        "fallback_used":   False,
        "shipment_id":     shipment_id,
    }
    agent_json = json.dumps(agent_preview)
    await redis_client.publish(f"agent_log:{tenant_id}", agent_json)
    await redis_client.lpush(f"agent_log:{tenant_id}", agent_json)
    await redis_client.ltrim(f"agent_log:{tenant_id}", 0, 99)
    log.info("fire.vrp_bg.complete", tenant_id=tenant_id, routes=len(alternate_routes))


async def _fetch_osrm_route(
    start_lon: float, start_lat: float, end_lon: float, end_lat: float
) -> list[list[float]]:
    """Fetch real road geometry from OSRM. Returns list of [lon, lat] pairs."""
    import httpx

    coord_str = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://router.project-osrm.org/route/v1/driving/{coord_str}",
                params={"overview": "full", "geometries": "geojson"},
                timeout=12.0,
            )
            resp.raise_for_status()
            data = resp.json()
        routes = data.get("routes", [])
        if routes:
            coords = routes[0].get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                return coords  # [[lon,lat], ...]
    except Exception as exc:
        log.warning("osrm.route_fetch_failed", error=str(exc))
    return [[start_lon, start_lat], [end_lon, end_lat]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_city(raw_city: str) -> str:
    return " ".join(raw_city.lower().replace(",", " ").split())


def _coords_for_city(city: str) -> tuple[float, float]:
    normalized = _normalize_city(city)
    if normalized in INDIAN_CITY_COORDS:
        return INDIAN_CITY_COORDS[normalized]
    if normalized.startswith("new "):
        normalized = normalized.removeprefix("new ").strip()
    return INDIAN_CITY_COORDS.get(normalized, (78.9629, 20.5937))


def _haversine_km(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
) -> float:
    radius_km = 6371.0
    d_lat = math.radians(end_lat - start_lat)
    d_lon = math.radians(end_lon - start_lon)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(start_lat))
        * math.cos(math.radians(end_lat))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _bind_tenant_rls(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        sa.text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _recent_shipments_stmt(tenant_id: str) -> sa.sql.Select:
    return (
        select(Shipment)
        .where(
            Shipment.tenant_id == tenant_id,
            Shipment.status != ShipmentStatus.CANCELLED,
        )
        .order_by(Shipment.created_at.desc())
        .limit(50)
    )


async def _seed_demo_shipments(
    db: AsyncSession,
    tenant_id: str,
    city_mode_pairs: list[tuple[str, str, ShipmentMode]],
) -> None:
    """Create exactly the 3 demo shipments needed (1 per transport mode)."""
    for origin, destination, mode in city_mode_pairs:
        tracking_num = (
            f"DEMO-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        )
        db.add(
            Shipment(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                tracking_num=tracking_num,
                origin=origin,
                destination=destination,
                sector="demo",
                mode=mode,
                status=ShipmentStatus.PENDING,
                risk_score=0.0,
                weight_kg=1000.0,
            )
        )
    await db.flush()


# ── Coastal waypoints for sea-route simulation (mirrors frontend routeGeometry.ts) ──
_COASTAL_NODES: list[list[float]] = [
    [69.0, 22.5], [71.5, 19.8], [72.0, 18.5], [72.8, 16.0], [73.2, 15.2],
    [74.0, 13.0], [75.2, 10.5], [76.0, 8.5],  [77.5, 7.0],  [78.8, 8.2],
    [79.8, 10.5], [80.8, 13.2], [82.0, 15.5], [83.5, 17.8], [85.5, 19.8],
    [87.5, 21.0], [89.0, 21.8],
]

_MAJOR_PORTS: list[dict] = [
    {"coords": [70.13, 23.00], "idx": 0},
    {"coords": [72.88, 19.08], "idx": 2},
    {"coords": [73.80, 15.40], "idx": 4},
    {"coords": [74.80, 12.87], "idx": 5},
    {"coords": [76.27, 9.93],  "idx": 6},
    {"coords": [78.18, 8.80],  "idx": 9},
    {"coords": [80.27, 13.08], "idx": 11},
    {"coords": [83.22, 17.69], "idx": 13},
    {"coords": [87.20, 20.47], "idx": 15},
    {"coords": [88.05, 22.00], "idx": 16},
]


def _nearest_port(lon: float, lat: float) -> dict:
    best = _MAJOR_PORTS[0]
    best_dist = float("inf")
    for p in _MAJOR_PORTS:
        d = math.sqrt((lon - p["coords"][0]) ** 2 + (lat - p["coords"][1]) ** 2)
        if d < best_dist:
            best_dist = d
            best = p
    return best


def _build_sea_coastal_path(
    start_lon: float, start_lat: float, end_lon: float, end_lat: float
) -> list[list[float]]:
    """Coastal waypoint path for sea shipments — mirrors frontend buildSeaPath()."""
    sp = _nearest_port(start_lon, start_lat)
    ep = _nearest_port(end_lon, end_lat)
    si, ei = sp["idx"], ep["idx"]
    lo, hi = min(si, ei), max(si, ei)
    coastal = _COASTAL_NODES[lo : hi + 1]
    if si > ei:
        coastal = list(reversed(coastal))
    # Inland approach legs (5-point linear interpolation each side)
    def lerp_leg(a: list[float], b: list[float], steps: int = 5) -> list[list[float]]:
        return [
            [a[0] + (b[0] - a[0]) * t / steps, a[1] + (b[1] - a[1]) * t / steps]
            for t in range(1, steps + 1)
        ]
    path = (
        lerp_leg([start_lon, start_lat], sp["coords"])
        + coastal
        + lerp_leg(ep["coords"], [end_lon, end_lat])
    )
    return [[round(p[0], 6), round(p[1], 6)] for p in path]


@dataclass
class SimulatedShipment:
    shipment_id: str
    tenant_id: str
    mode: ShipmentMode
    origin: str
    destination: str
    start_lon: float
    start_lat: float
    end_lon: float
    end_lat: float
    current_lon: float
    current_lat: float
    total_distance_km: float
    progress: float = 0.0
    route_path: list[list[float]] = field(default_factory=list)
    blocked: bool = False   # True when truck stops at fire location
    _path_index: float = 0.0

    def advance(self, speed_multiplier: float, tick_seconds: float) -> bool:
        # Frozen at fire location — don't move, don't complete
        if self.blocked:
            return False
        speed_kmh = MODE_SPEEDS_KMH.get(self.mode, 60.0)
        step_distance_km = speed_kmh * speed_multiplier * (tick_seconds / 3600.0)

        if self.total_distance_km <= 0:
            self.progress = 1.0
        else:
            delta = step_distance_km / self.total_distance_km
            self.progress = min(1.0, self.progress + delta)

        # Road and Sea: follow stored waypoints; Air: linear interpolation
        if self.route_path and len(self.route_path) >= 2 and self.mode in (
            ShipmentMode.ROAD, ShipmentMode.SEA
        ):
            idx = self.progress * (len(self.route_path) - 1)
            lo = int(idx)
            hi = min(lo + 1, len(self.route_path) - 1)
            frac = idx - lo
            self.current_lon = (
                self.route_path[lo][0] + (self.route_path[hi][0] - self.route_path[lo][0]) * frac
            )
            self.current_lat = (
                self.route_path[lo][1] + (self.route_path[hi][1] - self.route_path[lo][1]) * frac
            )
        else:
            self.current_lon = self.start_lon + (self.end_lon - self.start_lon) * self.progress
            self.current_lat = self.start_lat + (self.end_lat - self.start_lat) * self.progress
        return self.progress >= 1.0

    def payload(self, slim: bool = False) -> dict[str, Any]:
        return {
            "shipment_id": self.shipment_id,
            "mode": self.mode.value,
            "origin": self.origin,
            "destination": self.destination,
            "origin_lon": round(self.start_lon, 6),
            "origin_lat": round(self.start_lat, 6),
            "destination_lon": round(self.end_lon, 6),
            "destination_lat": round(self.end_lat, 6),
            "current_lon": round(self.current_lon, 6),
            "current_lat": round(self.current_lat, 6),
            "risk_score": 0.0,
            "status": (
                ShipmentStatus.DELIVERED.value
                if self.progress >= 1.0
                else ShipmentStatus.IN_TRANSIT.value
            ),
            "progress": round(self.progress, 4),
            # slim=True: omit route_path in regular ticks to keep WS frames small
            # (~2 KB vs ~700 KB). Frontend retains the last received path automatically.
            "route_path": (
                []
                if slim
                else (self.route_path if self.mode in (ShipmentMode.ROAD, ShipmentMode.SEA) else [])
            ),
        }


async def _prepare_simulation_shipments(
    db: AsyncSession,
    tenant_id: str,
    modes: list[str] | None = None,
) -> tuple[list[SimulatedShipment], int]:
    rows = (await db.execute(_recent_shipments_stmt(tenant_id))).scalars().all()
    seeded_count = 0

    # Full production demo: 9 shipments — 3 per transport mode
    _demo_target = 9

    if len(rows) < _demo_target:
        if settings.TESTING or settings.is_production:
            raise ValidationError(
                "At least 9 shipments are required to run the realtime simulation demo",
                field="shipments",
            )

        missing = _DEMO_SEED_PAIRS[len(rows) : _demo_target]
        await _seed_demo_shipments(db=db, tenant_id=tenant_id, city_mode_pairs=missing)
        rows = (await db.execute(_recent_shipments_stmt(tenant_id))).scalars().all()
        seeded_count = len(missing)
        log.info(
            "simulation.seeded_demo_shipments",
            tenant_id=tenant_id,
            seeded_count=seeded_count,
        )

    selected = rows[:_demo_target]
    simulations: list[SimulatedShipment] = []

    for idx, shipment in enumerate(selected):
        # Force the 9 demo slots to exactly match our 3 road, 3 air, 3 sea pairs
        demo_origin, demo_dest, demo_mode = _DEMO_SEED_PAIRS[idx % len(_DEMO_SEED_PAIRS)]
        
        start_lon, start_lat = _coords_for_city(demo_origin)
        end_lon, end_lat = _coords_for_city(demo_dest)
        distance = _haversine_km(start_lon, start_lat, end_lon, end_lat)

        shipment.origin = demo_origin
        shipment.destination = demo_dest
        shipment.mode = demo_mode
        shipment.status = ShipmentStatus.IN_TRANSIT
        shipment.risk_score = 0.0
        shipment.current_lon = start_lon
        shipment.current_lat = start_lat

        simulations.append(
            SimulatedShipment(
                shipment_id=str(shipment.id),
                tenant_id=tenant_id,
                mode=demo_mode,
                origin=shipment.origin,
                destination=shipment.destination,
                start_lon=start_lon,
                start_lat=start_lat,
                end_lon=end_lon,
                end_lat=end_lat,
                current_lon=start_lon,
                current_lat=start_lat,
                total_distance_km=distance,
            )
        )

    # Fetch OSRM routes for road shipments concurrently
    road_sims = [s for s in simulations if s.mode == ShipmentMode.ROAD]
    if road_sims:
        routes = await asyncio.gather(
            *[_fetch_osrm_route(s.start_lon, s.start_lat, s.end_lon, s.end_lat)
              for s in road_sims],
            return_exceptions=True,
        )
        for sim, route in zip(road_sims, routes):
            if isinstance(route, list):
                sim.route_path = route

    # Build coastal paths for sea shipments — pure port-to-port, no inland legs
    for sim in simulations:
        if sim.mode == ShipmentMode.SEA:
            sp = _nearest_port(sim.start_lon, sim.start_lat)
            ep = _nearest_port(sim.end_lon, sim.end_lat)
            # Snap ship start/end to PORT coordinates so it stays in water
            sim.start_lon, sim.start_lat = sp["coords"]
            sim.end_lon, sim.end_lat = ep["coords"]
            sim.current_lon, sim.current_lat = sp["coords"]
            # Pure coastal waypoints — no lerp legs over land
            si, ei = sp["idx"], ep["idx"]
            lo, hi = min(si, ei), max(si, ei)
            coastal: list[list[float]] = list(_COASTAL_NODES[lo:hi + 1])
            if si > ei:
                coastal = list(reversed(coastal))
            if len(coastal) < 2:
                # If same port, add one intermediate coastal node
                coastal = [sp["coords"], _COASTAL_NODES[max(0, sp["idx"] - 1)], ep["coords"]]
            sim.route_path = [[round(p[0], 6), round(p[1], 6)] for p in coastal]
            # Recalculate distance along coastal path
            sim.total_distance_km = sum(
                _haversine_km(coastal[i][0], coastal[i][1], coastal[i + 1][0], coastal[i + 1][1])
                for i in range(len(coastal) - 1)
            )
    if modes:
        simulations = [s for s in simulations if s.mode.value in modes]

    await db.commit()

    # Store demo shipment IDs in Redis (TTL 4h) so WS can filter to only these
    demo_ids = [s.shipment_id for s in simulations]
    demo_key = f"demo_shipments:{tenant_id}"
    await redis_client.delete(demo_key)
    if demo_ids:
        await redis_client.sadd(demo_key, *demo_ids)
        await redis_client.expire(demo_key, 14400)  # 4 hours

    return simulations, seeded_count


async def _persist_positions(
    tenant_id: str,
    simulated: list[SimulatedShipment],
) -> None:
    async with AsyncSessionLocal() as session:
        await _bind_tenant_rls(session, tenant_id)
        for point in simulated:
            status = (
                ShipmentStatus.DELIVERED if point.progress >= 1.0 else ShipmentStatus.IN_TRANSIT
            )
            await session.execute(
                sa.update(Shipment)
                .where(
                    Shipment.id == point.shipment_id,
                    Shipment.tenant_id == tenant_id,
                )
                .values(
                    current_lat=point.current_lat,
                    current_lon=point.current_lon,
                    status=status,
                    risk_score=0.0,
                )
            )
        await session.commit()


async def _run_simulation_worker(
    tenant_id: str,
    simulated: list[SimulatedShipment],
    speed_multiplier: float,
) -> None:
    channel = f"shipments:{tenant_id}"
    tick_seconds = settings.SIMULATION_DEMO_TICK_SECONDS
    if settings.TESTING:
        tick_seconds = min(tick_seconds, 0.1)

    try:
        await redis_client.publish(
            channel,
            json.dumps(
                {
                    "type": "simulation_started",
                    "shipments": [point.payload() for point in simulated],
                    "ts": _utc_now(),
                }
            ),
        )

        while True:
            completed = 0
            current_speed = _simulation_speed.get(tenant_id, speed_multiplier)
            fire = _active_fire.get(tenant_id)

            for point in simulated:
                if point.advance(speed_multiplier=current_speed, tick_seconds=tick_seconds):
                    completed += 1

                # Block truck at DECISION POINT (40km before fire).
                # Short-circuit: fire.get() only runs when fire is not None.
                if (
                    fire
                    and not point.blocked
                    and point.shipment_id == fire.get("shipment_id")
                    and point.progress >= (
                        fire.get("decision_progress", fire.get("fire_progress", 1.0))
                        - _FIRE_STOP_BUFFER
                    )
                ):
                    point.blocked = True
                    await redis_client.publish(
                        channel,
                        json.dumps({
                            "type": "truck_at_fire",
                            "shipment_id": point.shipment_id,
                            "origin": point.origin,
                            "destination": point.destination,
                            "fire_lat": fire.get("fire_lat"),
                            "fire_lon": fire.get("fire_lon"),
                            "decision_lat": fire.get("decision_lat"),
                            "decision_lon": fire.get("decision_lon"),
                            "ts": _utc_now(),
                        }),
                    )
                    log.info("simulation.truck_blocked_at_decision_point", tenant_id=tenant_id, shipment_id=point.shipment_id)

            await _persist_positions(tenant_id=tenant_id, simulated=simulated)

            await redis_client.publish(
                channel,
                json.dumps(
                    {
                        "type": "simulation_tick",
                        # slim=True: skip route_path (700 KB → 2 KB per tick)
                        "shipments": [point.payload(slim=True) for point in simulated],
                        "ts": _utc_now(),
                    }
                ),
            )

            if completed == len(simulated):
                break

            await asyncio.sleep(tick_seconds)

        await redis_client.publish(
            channel,
            json.dumps(
                {
                    "type": "simulation_completed",
                    "shipments": [point.payload() for point in simulated],
                    "ts": _utc_now(),
                }
            ),
        )
    except asyncio.CancelledError:
        await redis_client.publish(
            channel,
            json.dumps(
                {
                    "type": "simulation_cancelled",
                    "ts": _utc_now(),
                }
            ),
        )
        log.info("simulation.cancelled", tenant_id=tenant_id)
        raise
    except Exception as exc:  # noqa: BLE001
        log.error("simulation.failed", tenant_id=tenant_id, error=str(exc), exc_info=True)
        await redis_client.publish(
            channel,
            json.dumps(
                {
                    "type": "simulation_error",
                    "message": "Simulation worker failed",
                    "ts": _utc_now(),
                }
            ),
        )
    finally:
        async with _simulation_lock:
            task = _simulation_tasks.get(tenant_id)
            if task is not None and task == asyncio.current_task():
                _simulation_tasks.pop(tenant_id, None)


operator_user_dependency = require_role(UserRole.OPERATOR)


@router.post("/demo")
async def start_simulation_demo(
    user: Annotated[User, Depends(operator_user_dependency)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    restart: bool = Query(False, description="Cancel and restart an existing simulation"),
    modes: str | None = Query(None, description="Comma-separated list of transport modes to simulate"),
    speed_multiplier: float | None = Query(
        None,
        gt=1.0,
        le=100000.0,
        description="Demo speed multiplier applied to base transport speeds",
    ),
) -> dict[str, Any]:
    tenant_id = str(user.tenant_id)
    demo_multiplier = speed_multiplier or settings.SIMULATION_DEMO_SPEED_MULTIPLIER

    async with _simulation_lock:
        existing_task = _simulation_tasks.get(tenant_id)
        if existing_task and not existing_task.done():
            if not restart:
                return {
                    "status": "already_running",
                    "tenant_id": tenant_id,
                    "channel": f"shipments:{tenant_id}",
                }
            existing_task.cancel()

    # Clear old fire events and stale VRP cache when re-simulating
    _active_fire.pop(tenant_id, None)
    await redis_client.delete(f"vrp_results:{tenant_id}:latest")  # FIX: correct key
    clear_event = json.dumps({"type": "fire_cleared"})
    await redis_client.publish(f"shipments:{tenant_id}", clear_event)

    modes_list = [m.strip().lower() for m in modes.split(",")] if modes else None
    simulated, seeded_count = await _prepare_simulation_shipments(
        db=db, tenant_id=tenant_id, modes=modes_list
    )

    task = asyncio.create_task(
        _run_simulation_worker(
            tenant_id=tenant_id,
            simulated=simulated,
            speed_multiplier=demo_multiplier,
        )
    )

    async with _simulation_lock:
        _simulation_tasks[tenant_id] = task

    # Store for disruption endpoint
    _active_simulations[tenant_id] = simulated

    # Count actual mode distribution (not a dict comprehension that hardcodes 1)
    mode_counts: dict[str, int] = {}
    for s in simulated:
        mode_counts[s.mode.value] = mode_counts.get(s.mode.value, 0) + 1
    return {
        "status": "started",
        "tenant_id": tenant_id,
        "channel": f"shipments:{tenant_id}",
        "selected_shipments": len(simulated),
        "seeded_shipments": seeded_count,
        "selected_shipment_ids": [point.shipment_id for point in simulated],
        "mode_distribution": mode_counts,
        "speed_multiplier": demo_multiplier,
        "tick_seconds": settings.SIMULATION_DEMO_TICK_SECONDS,
    }


@router.patch("/speed")
async def update_simulation_speed(
    user: Annotated[User, Depends(operator_user_dependency)],
    speed_multiplier: float = Query(
        ...,
        gt=1.0,
        le=100000.0,
        description="Demo speed multiplier applied to base transport speeds",
    ),
) -> dict[str, Any]:
    """Dynamically update the speed of the running simulation without restarting."""
    tenant_id = str(user.tenant_id)
    _simulation_speed[tenant_id] = speed_multiplier
    return {
        "status": "success",
        "tenant_id": tenant_id,
        "speed_multiplier": speed_multiplier,
    }


@router.post("/disruption/fire")
async def simulate_fire_disruption(
    user: Annotated[User, Depends(operator_user_dependency)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Trigger a fire disruption on the active road shipment.

    Flow:
      1. Compute fire location (25% ahead on route_path for visible drama).
      2. Call OSRM /route?alternatives=true for immediate VRP results (<2s).
      3. Publish fire_event to shipments:{tenant_id} so the map shows the fire marker.
      4. Publish VRP results immediately to vrp_results:{tenant_id} for Route Optimizer.
      5. Publish to `disruptions` channel so Gemini Decision Agent runs asynchronously.
      6. Publish preview to agent_log for immediate dashboard feedback.
    """
    tenant_id = str(user.tenant_id)
    if tenant_id in _active_fire:
        old_fire = _active_fire.pop(tenant_id)
        # FIX: both calls must be awaited; key must include :latest suffix
        clear_event = json.dumps({
            "type": "fire_cleared",
            "shipment_id": old_fire.get("shipment_id")
        })
        await redis_client.publish(f"shipments:{tenant_id}", clear_event)
        await redis_client.delete(f"vrp_results:{tenant_id}:latest")

    sims = _active_simulations.get(tenant_id, [])
    road_sims = [s for s in sims if s.mode == ShipmentMode.ROAD and s.progress < 1.0]

    if not road_sims:
        return {
            "status": "error",
            "message": "No active road shipments found. Start simulation first.",
        }

    import random
    road_ship = random.choice(road_sims)

    # ── 1. Pick fire point ~25% ahead on route ──
    BYPASS_KM = _FIRE_BYPASS_KM     # module-level constant (shared with worker)
    STOP_BUFFER = _FIRE_STOP_BUFFER  # noqa: F841  (used in worker, defined here for readability)

    if road_ship.route_path and len(road_ship.route_path) >= 4:
        fire_progress = min(road_ship.progress + 0.25, 0.80)
        path = road_ship.route_path
        n_pts = len(path)
        idx_f = fire_progress * (n_pts - 1)
        lo = int(idx_f)
        hi = min(lo + 1, n_pts - 1)
        frac = idx_f - lo
        fire_lon = path[lo][0] + (path[hi][0] - path[lo][0]) * frac
        fire_lat = path[lo][1] + (path[hi][1] - path[lo][1]) * frac

        # ── Decision / bypass point: BYPASS_KM before the fire on the route ──
        # The alternate green route originates here. The truck will also stop
        # here if no reroute action is taken by the operator.
        total_route_km = sum(
            _haversine_km(path[k][0], path[k][1], path[k+1][0], path[k+1][1])
            for k in range(n_pts - 1)
        ) or 1.0
        fire_dist_km = fire_progress * total_route_km
        truck_dist_km = road_ship.progress * total_route_km
        # Decision point = BYPASS_KM before fire, at minimum 5 km ahead of truck
        decision_dist_km = max(fire_dist_km - BYPASS_KM, truck_dist_km + 5.0)
        decision_progress = min(
            max(decision_dist_km / total_route_km, road_ship.progress + 0.02),
            fire_progress - 0.03,
        )
        idx_d = decision_progress * (n_pts - 1)
        lo_d, hi_d = int(idx_d), min(int(idx_d) + 1, n_pts - 1)
        frac_d = idx_d - lo_d
        decision_lon = path[lo_d][0] + (path[hi_d][0] - path[lo_d][0]) * frac_d
        decision_lat = path[lo_d][1] + (path[hi_d][1] - path[lo_d][1]) * frac_d
    else:
        fire_progress = min(road_ship.progress + 0.25, 0.80)
        fire_lon = road_ship.current_lon
        fire_lat = road_ship.current_lat
        decision_progress = max(road_ship.progress + 0.05, fire_progress - 0.15)
        t = decision_progress
        decision_lon = road_ship.start_lon + (road_ship.end_lon - road_ship.start_lon) * t
        decision_lat = road_ship.start_lat + (road_ship.end_lat - road_ship.start_lat) * t

    fire_lon = round(fire_lon, 4)
    fire_lat = round(fire_lat, 4)
    decision_lon = round(decision_lon, 4)
    decision_lat = round(decision_lat, 4)
    event_id = f"fire-{uuid.uuid4().hex[:8]}"

    disruption_desc = (
        f"Fire detected on route {road_ship.origin} → {road_ship.destination} "
        f"near ({fire_lat:.2f}°N, {fire_lon:.2f}°E). "
        f"Bypass decision point {BYPASS_KM:.0f} km ahead of fire."
    )

    disruption_event = {
        "event_id":             event_id,
        "event_type":           "fire",
        "severity":             "critical",
        "description":          disruption_desc,
        "timestamp":            _utc_now(),
        "lat":                  fire_lat,
        "lon":                  fire_lon,
        "segment_id":           f"{fire_lat:.4f},{fire_lon:.4f}",
        "highway_code":         f"NH-{road_ship.origin[:2].upper()}{road_ship.destination[:2].upper()}",
        "affected_segment_ids": [f"{fire_lat:.4f},{fire_lon:.4f}"],
        "shipment_id":          road_ship.shipment_id,
        "tenant_id":            tenant_id,
    }

    # ── Store fire state NOW so the worker immediately starts monitoring the truck ──
    _active_fire[tenant_id] = {
        "shipment_id":       road_ship.shipment_id,
        "fire_progress":     fire_progress,
        "fire_lat":          fire_lat,
        "fire_lon":          fire_lon,
        "decision_progress": decision_progress,
        "decision_lat":      decision_lat,
        "decision_lon":      decision_lon,
        "event_id":          event_id,
    }

    # ── Publish fire marker immediately (<100 ms) ──
    await redis_client.publish(
        f"shipments:{tenant_id}",
        json.dumps({
            "type":        "fire_event",
            "fire_lon":    fire_lon,
            "fire_lat":    fire_lat,
            "shipment_id": road_ship.shipment_id,
            "description": disruption_desc,
            "event_id":    event_id,
        }),
    )

    # ── OSRM + VRP in background — endpoint returns NOW, trucks keep moving ──
    asyncio.create_task(
        _fire_vrp_background_task(
            tenant_id=tenant_id,
            shipment_id=road_ship.shipment_id,
            event_id=event_id,
            disruption_desc=disruption_desc,
            disruption_event=disruption_event,
            r_lon=decision_lon, r_lat=decision_lat,
            d_lon=road_ship.end_lon, d_lat=road_ship.end_lat,
            fire_lat=fire_lat, fire_lon=fire_lon,
            decision_progress=decision_progress,
            fire_progress=fire_progress,
            decision_lon=decision_lon, decision_lat=decision_lat,
            origin=road_ship.origin, destination=road_ship.destination,
        )
    )

    # ── Update DB Status to At Risk ──
    await db.execute(
        sa.update(Shipment)
        .where(Shipment.id == road_ship.shipment_id)
        .values(status=ShipmentStatus.AT_RISK)
    )
    await db.commit()

    log.info(
        "simulation.fire_disruption_triggered",
        tenant_id=tenant_id,
        shipment_id=road_ship.shipment_id,
        fire_lat=fire_lat,
        fire_lon=fire_lon,
    )

    return {
        "status":      "triggered",
        "shipment_id": road_ship.shipment_id,
        "shipment_origin":      road_ship.origin,
        "shipment_destination": road_ship.destination,
        "fire_lat":   fire_lat,
        "fire_lon":   fire_lon,
        "decision_lat": decision_lat,
        "decision_lon": decision_lon,
        "vrp_status": "computing_in_background",
    }


@router.post("/disruption/apply-route")
async def apply_reroute(
    user: Annotated[User, Depends(operator_user_dependency)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    route_index: int = Body(0, embed=True),
) -> dict[str, Any]:
    """Apply a dispatched alternate route to the active road shipment.

    Fetches the full OSRM geometry for the chosen alternate route index,
    updates the in-memory SimulatedShipment route_path, and publishes a
    fire_cleared + simulation_tick event so the map updates in real-time.
    """
    import httpx

    tenant_id = str(user.tenant_id)
    sims = _active_simulations.get(tenant_id, [])
    
    # ── Identify the correct shipment that is experiencing the fire ──
    fire_info = _active_fire.get(tenant_id)
    target_shipment_id = fire_info.get("shipment_id") if fire_info else None
    
    if target_shipment_id:
        road_ship = next((s for s in sims if s.shipment_id == target_shipment_id), None)
    else:
        # Fallback if fire state was somehow lost
        road_ship = next((s for s in sims if s.mode == ShipmentMode.ROAD and s.progress < 1.0), None)

    if not road_ship:
        return {"status": "error", "message": "No active disrupted shipment found."}

    # Allow reroute if:
    #   a) truck is blocked (stopped at decision point) — always valid
    #   b) fire is active and truck hasn’t passed the bypass decision point yet
    # fire_info may be None after a backend restart; road_ship.blocked is the
    # reliable fallback in that case.
    fire_info = _active_fire.get(tenant_id)
    decision_progress = fire_info.get("decision_progress", 1.0) if fire_info else 1.0

    if not road_ship.blocked and (not fire_info or road_ship.progress > decision_progress + 0.03):
        return {
            "status": "error",
            "message": (
                "No active fire disruption, or truck already passed the bypass point. "
                "Trigger a fire simulation first."
            ),
        }

    # ── Reroute from CURRENT truck position (works whether moving or stopped) ──
    c_lon = road_ship.current_lon
    c_lat = road_ship.current_lat
    curr_idx = int(road_ship.progress * (len(road_ship.route_path) - 1)) if road_ship.route_path else 0

    new_path: list[list[float]] = []

    # Fetch exactly the same geometry that was shown on the map
    vrp_json = await redis_client.get(f"vrp_results:{tenant_id}:latest")
    if vrp_json:
        try:
            data = json.loads(vrp_json)
            alts = data.get("alternate_routes", {}).get(road_ship.shipment_id, [])
            if 0 <= route_index < len(alts):
                new_path = alts[route_index].get("geometry", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("apply_reroute.read_vrp_failed", error=str(exc))

    osrm_fallback_used = False
    if not new_path or len(new_path) < 2:
        osrm_fallback_used = True
        # Fallback to raw OSRM if Redis fetch failed
        coord_str = f"{c_lon},{c_lat};{road_ship.end_lon},{road_ship.end_lat}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://router.project-osrm.org/route/v1/driving/{coord_str}",
                    params={"overview": "full", "geometries": "geojson", "alternatives": "true"},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
            routes = data.get("routes", [])
            # Prefer alternate route (index 1); fall back to primary (index 0)
            target_idx = min(route_index + 1, len(routes) - 1) if len(routes) > 1 else 0
            chosen = routes[target_idx]
            new_path = chosen.get("geometry", {}).get("coordinates", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("apply_reroute.osrm_failed", error=str(exc))

    if len(new_path) < 2:
        osrm_fallback_used = True
        # Fallback: straight line from current position to destination
        new_path = [
            [c_lon, c_lat],
            [road_ship.end_lon, road_ship.end_lat],
        ]

    # Splice the new path onto the existing route to preserve the visual trail!
    if road_ship.route_path:
        if osrm_fallback_used:
            # Fallback path starts at truck's current location
            splice_idx = curr_idx
        else:
            # VRP path starts at the bypass decision point
            splice_idx = int(fire_info.get("decision_progress", 1.0) * (len(road_ship.route_path) - 1)) if fire_info else curr_idx
            splice_idx = max(curr_idx, splice_idx)
            
        full_new_path = road_ship.route_path[:splice_idx] + new_path
    else:
        full_new_path = new_path

    # Update SimulatedShipment
    road_ship.route_path = full_new_path
    
    # Recalculate progress so the truck stays exactly where it was at curr_idx
    if len(full_new_path) > 1:
        road_ship.progress = curr_idx / (len(full_new_path) - 1)
        road_ship.total_distance_km = sum(
            _haversine_km(
                full_new_path[i][0], full_new_path[i][1],
                full_new_path[i + 1][0], full_new_path[i + 1][1],
            )
            for i in range(len(full_new_path) - 1)
        )
    else:
        road_ship.progress = 1.0
        road_ship.total_distance_km = max(1.0, _haversine_km(c_lon, c_lat, road_ship.end_lon, road_ship.end_lat))

    # Note: We specifically DO NOT overwrite road_ship.start_lon or start_lat
    # so that the payload origin remains intact and the truck doesn't teleport.
    road_ship.blocked = False

    # Clear the active fire state + stale VRP cache
    _active_fire.pop(tenant_id, None)
    # FIX Bug 3: delete cached VRP result so reconnecting WS clients don't
    # re-receive and re-render the old green alternate route overlay.
    await redis_client.delete(f"vrp_results:{tenant_id}:latest")

    channel = f"shipments:{tenant_id}"

    # 1. Clear the fire marker from the map
    await redis_client.publish(
        channel,
        json.dumps(
            {
                "type": "fire_cleared",
                "shipment_id": road_ship.shipment_id,
            }
        ),
    )

    # 2. Push FULL tick for ALL active ships so the new route_path is immediately
    # available on the frontend — even after a page navigate (FreightMap remount).
    all_sims = _active_simulations.get(tenant_id, [])
    await redis_client.publish(
        channel,
        json.dumps(
            {
                "type": "simulation_tick",
                "shipments": [
                    s.payload(slim=False) if s.shipment_id == road_ship.shipment_id
                    else s.payload(slim=True)
                    for s in all_sims
                ] or [road_ship.payload(slim=False)],
                "ts": _utc_now(),
            }
        ),
    )

    # 3. Log reroute decision to agent_log
    reroute_log = {
        "trace_id": f"reroute-{uuid.uuid4().hex[:6]}",
        "timestamp": _utc_now(),
        "description": f"Reroute dispatched for {road_ship.origin}→{road_ship.destination} (alt route #{route_index + 1})",  # noqa: E501
        "severity": "info",
        "message": f"✅ Dispatch confirmed. Road shipment now following alternate route #{route_index + 1} ({len(new_path)} waypoints).",  # noqa: E501
        "actions": ["reroute_applied", "fire_cleared"],
        "human_escalated": False,
        "fallback_used": False,
        "shipment_id": road_ship.shipment_id,
    }
    reroute_json = json.dumps(reroute_log)
    await redis_client.publish(f"agent_log:{tenant_id}", reroute_json)
    await redis_client.lpush(f"agent_log:{tenant_id}", reroute_json)
    await redis_client.ltrim(f"agent_log:{tenant_id}", 0, 99)

    log.info(
        "simulation.reroute_applied",
        tenant_id=tenant_id,
        shipment_id=road_ship.shipment_id,
        route_index=route_index,
        waypoints=len(new_path),
    )

    # ── Update DB Status to Rerouted ──
    await db.execute(
        sa.update(Shipment)
        .where(Shipment.id == road_ship.shipment_id)
        .values(status=ShipmentStatus.REROUTED)
    )
    await db.commit()

    return {
        "status": "rerouted",
        "shipment_id": road_ship.shipment_id,
        "route_index": route_index,
        "new_waypoints": len(new_path),
    }


@router.patch("/speed")
async def update_simulation_speed(
    user: Annotated[User, Depends(operator_user_dependency)],
    speed_multiplier: float = Query(..., gt=1.0, le=100000.0, description="New speed multiplier"),
) -> dict[str, Any]:
    """Update speed of the running simulation without restarting it."""
    tenant_id = str(user.tenant_id)
    task = _simulation_tasks.get(tenant_id)
    if not task or task.done():
        return {"status": "no_simulation", "message": "No active simulation found."}
    _simulation_speed[tenant_id] = speed_multiplier
    log.info("simulation.speed_updated", tenant_id=tenant_id, speed_multiplier=speed_multiplier)
    return {"status": "updated", "speed_multiplier": speed_multiplier}

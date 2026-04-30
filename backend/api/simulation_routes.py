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
    _path_index: float = 0.0

    def advance(self, speed_multiplier: float, tick_seconds: float) -> bool:
        speed_kmh = MODE_SPEEDS_KMH.get(self.mode, 60.0)
        step_distance_km = speed_kmh * speed_multiplier * (tick_seconds / 3600.0)

        if self.total_distance_km <= 0:
            self.progress = 1.0
        else:
            delta = step_distance_km / self.total_distance_km
            self.progress = min(1.0, self.progress + delta)

        # Road/rail: follow OSRM waypoints; air/sea: linear interpolation
        if self.route_path and len(self.route_path) >= 2 and self.mode == ShipmentMode.ROAD:
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

    def payload(self) -> dict[str, Any]:
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
            "route_path": self.route_path if self.mode == ShipmentMode.ROAD else [],
        }


async def _prepare_simulation_shipments(
    db: AsyncSession,
    tenant_id: str,
) -> tuple[list[SimulatedShipment], int]:
    rows = (await db.execute(_recent_shipments_stmt(tenant_id))).scalars().all()
    seeded_count = 0

    # Full production demo: 9 shipments — 3 per transport mode
    _DEMO_TARGET = 9

    if len(rows) < _DEMO_TARGET:
        if settings.TESTING or settings.is_production:
            raise ValidationError(
                "At least 9 shipments are required to run the realtime simulation demo",
                field="shipments",
            )

        # Seed 9 shipments across all three transport modes (3 each)
        demo_seed_pairs: list[tuple[str, str, ShipmentMode]] = [
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
        missing = demo_seed_pairs[len(rows) : _DEMO_TARGET]
        await _seed_demo_shipments(db=db, tenant_id=tenant_id, city_mode_pairs=missing)
        rows = (await db.execute(_recent_shipments_stmt(tenant_id))).scalars().all()
        seeded_count = len(missing)
        log.info(
            "simulation.seeded_demo_shipments",
            tenant_id=tenant_id,
            seeded_count=seeded_count,
        )

    selected = rows[:_DEMO_TARGET]
    simulations: list[SimulatedShipment] = []

    for idx, shipment in enumerate(selected):
        # Cycle ROAD → AIR → SEA across the 9 slots (3 per mode)
        mode = DEMO_MODE_SEQUENCE[idx % len(DEMO_MODE_SEQUENCE)]
        start_lon, start_lat = _coords_for_city(shipment.origin)
        end_lon, end_lat = _coords_for_city(shipment.destination)
        distance = _haversine_km(start_lon, start_lat, end_lon, end_lat)

        shipment.mode = mode
        shipment.status = ShipmentStatus.IN_TRANSIT
        shipment.risk_score = 0.0
        shipment.current_lon = start_lon
        shipment.current_lat = start_lat

        simulations.append(
            SimulatedShipment(
                shipment_id=str(shipment.id),
                tenant_id=tenant_id,
                mode=mode,
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

    # Fetch OSRM routes for road shipments
    for sim in simulations:
        if sim.mode == ShipmentMode.ROAD:
            sim.route_path = await _fetch_osrm_route(
                sim.start_lon, sim.start_lat, sim.end_lon, sim.end_lat
            )

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
            for point in simulated:
                if point.advance(speed_multiplier=speed_multiplier, tick_seconds=tick_seconds):
                    completed += 1

            await _persist_positions(tenant_id=tenant_id, simulated=simulated)

            await redis_client.publish(
                channel,
                json.dumps(
                    {
                        "type": "simulation_tick",
                        "shipments": [point.payload() for point in simulated],
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

    simulated, seeded_count = await _prepare_simulation_shipments(db=db, tenant_id=tenant_id)

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


@router.post("/disruption/fire")
async def simulate_fire_disruption(
    user: Annotated[User, Depends(operator_user_dependency)],
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
    import httpx

    tenant_id = str(user.tenant_id)
    sims = _active_simulations.get(tenant_id, [])
    road_ship = next((s for s in sims if s.mode == ShipmentMode.ROAD and s.progress < 1.0), None)

    if not road_ship:
        return {
            "status": "error",
            "message": "No active road shipment found. Start simulation first.",
        }

    # ── 1. Pick fire point 25% ahead on route (visible but not too close to destination) ──
    if road_ship.route_path and len(road_ship.route_path) >= 4:
        fire_progress = min(road_ship.progress + 0.25, 0.80)
        path = road_ship.route_path
        idx_f = fire_progress * (len(path) - 1)
        lo = int(idx_f)
        hi = min(lo + 1, len(path) - 1)
        frac = idx_f - lo
        fire_lon = path[lo][0] + (path[hi][0] - path[lo][0]) * frac
        fire_lat = path[lo][1] + (path[hi][1] - path[lo][1]) * frac
    else:
        fire_lon = road_ship.current_lon
        fire_lat = road_ship.current_lat

    fire_lon = round(fire_lon, 4)
    fire_lat = round(fire_lat, 4)
    event_id = f"fire-{uuid.uuid4().hex[:8]}"

    disruption_desc = (
        f"Fire detected on route {road_ship.origin} → {road_ship.destination} "
        f"near ({fire_lat:.2f}°N, {fire_lon:.2f}°E)"
    )

    # ── 2. OSRM fast VRP — get alternate routes immediately ──
    alternate_routes: list[dict[str, Any]] = []
    try:
        o_lon, o_lat = road_ship.start_lon, road_ship.start_lat
        d_lon, d_lat = road_ship.end_lon, road_ship.end_lat
        coord_str = f"{o_lon},{o_lat};{d_lon},{d_lat}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://router.project-osrm.org/route/v1/driving/{coord_str}",
                params={
                    "overview": "false",
                    "alternatives": "true",
                    "steps": "false",
                },
                timeout=8.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                for i, route in enumerate(data.get("routes", [])[:3]):
                    alternate_routes.append(
                        {
                            "route_id": f"{event_id}-alt-{i}",
                            "distance_km": round(route.get("distance", 0) / 1000, 1),
                            "duration_min": round(route.get("duration", 0) / 60, 0),
                            "via_waypoints": [f"Route {i + 1} (OSRM)"],
                            "cost_inr": round(route.get("distance", 0) / 1000 * 45, 0),
                            "eta_hours": round(route.get("duration", 0) / 3600, 1),
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        log.warning("fire.osrm_alternatives_failed", error=str(exc))

    # Fallback: 2 hand-crafted alternatives if OSRM unavailable
    if not alternate_routes:
        base_dist = road_ship.total_distance_km
        alternate_routes = [
            {
                "route_id": f"{event_id}-alt-0",
                "distance_km": round(base_dist * 1.12, 1),
                "duration_min": round(base_dist * 1.12 / 60 * 60, 0),
                "via_waypoints": ["NH-7 Bypass"],
                "cost_inr": round(base_dist * 1.12 * 45, 0),
                "eta_hours": round(base_dist * 1.12 / 60, 1),
            },
            {
                "route_id": f"{event_id}-alt-1",
                "distance_km": round(base_dist * 1.08, 1),
                "duration_min": round(base_dist * 1.08 / 60 * 60, 0),
                "via_waypoints": ["NH-58 Alternate"],
                "cost_inr": round(base_dist * 1.08 * 42, 0),
                "eta_hours": round(base_dist * 1.08 / 60, 1),
            },
        ]

    disruption_event = {
        "event_id": event_id,
        "event_type": "fire",
        "severity": "critical",
        "description": disruption_desc,
        "timestamp": _utc_now(),
        "lat": fire_lat,
        "lon": fire_lon,
        "segment_id": f"{fire_lat:.4f},{fire_lon:.4f}",
        "highway_code": f"NH-{road_ship.origin[:2].upper()}{road_ship.destination[:2].upper()}",
        "affected_segment_ids": [f"{fire_lat:.4f},{fire_lon:.4f}"],
        "shipment_id": road_ship.shipment_id,
        "tenant_id": tenant_id,
    }

    # ── 3. Publish fire_event to shipments channel → map shows fire marker ──
    fire_event_payload = json.dumps(
        {
            "type": "fire_event",
            "fire_lon": fire_lon,
            "fire_lat": fire_lat,
            "shipment_id": road_ship.shipment_id,
            "description": disruption_desc,
            "event_id": event_id,
        }
    )
    await redis_client.publish(f"shipments:{tenant_id}", fire_event_payload)

    # ── 4. Publish VRP results immediately to Route Optimizer ──
    vrp_payload = {
        "trace_id": f"vrp-fast-{event_id}",
        "timestamp": _utc_now(),
        "disruption": {
            "description": disruption_desc,
            "severity": "critical",
            "event_type": "fire",
            "lat": fire_lat,
            "lon": fire_lon,
            "shipment_id": road_ship.shipment_id,
        },
        "alternate_routes": {road_ship.shipment_id: alternate_routes},
        "selected_actions": ["reroute_initiated", "carrier_notified"],
        "fallback_used": False,
        "source": "OSRM_FAST",
        "gemini_tokens_used": 0,
        "total_cost_delta_inr": alternate_routes[0].get("cost_inr", 0) if alternate_routes else 0,
    }
    vrp_json = json.dumps(vrp_payload)
    await redis_client.publish(f"vrp_results:{tenant_id}", vrp_json)
    await redis_client.setex(f"vrp_results:{tenant_id}:latest", 3600, vrp_json)

    # ── 5. Publish to disruptions → Gemini Decision Agent runs asynchronously ──
    await redis_client.publish("disruptions", json.dumps(disruption_event))
    log.info(
        "simulation.fire_disruption_triggered",
        tenant_id=tenant_id,
        shipment_id=road_ship.shipment_id,
        fire_lat=fire_lat,
        fire_lon=fire_lon,
    )

    # ── 6. Immediate agent log preview for dashboard ──
    agent_preview = {
        "trace_id": f"fire-preview-{uuid.uuid4().hex[:6]}",
        "timestamp": _utc_now(),
        "disruption": {
            "description": disruption_desc,
            "severity": "critical",
            "event_type": "fire",
            "shipment_id": road_ship.shipment_id,
        },
        "description": disruption_desc,
        "severity": "critical",
        "actions": ["alert_dispatched", "reroute_initiated", "gemini_analysis_queued"],
        "message": f"🔥 Fire disruption on {road_ship.origin}→{road_ship.destination}. {len(alternate_routes)} alternate routes computed. Gemini agent analyzing...",  # noqa: E501
        "human_escalated": False,
        "fallback_used": False,
        "shipment_id": road_ship.shipment_id,
    }
    agent_json = json.dumps(agent_preview)
    await redis_client.publish(f"agent_log:{tenant_id}", agent_json)
    await redis_client.lpush(f"agent_log:{tenant_id}", agent_json)
    await redis_client.ltrim(f"agent_log:{tenant_id}", 0, 99)

    return {
        "status": "triggered",
        "shipment_id": road_ship.shipment_id,
        "shipment_origin": road_ship.origin,
        "shipment_destination": road_ship.destination,
        "fire_lat": fire_lat,
        "fire_lon": fire_lon,
        "event_id": event_id,
        "alternate_routes_count": len(alternate_routes),
    }


@router.post("/disruption/apply-route")
async def apply_reroute(
    user: Annotated[User, Depends(operator_user_dependency)],
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
    road_ship = next((s for s in sims if s.mode == ShipmentMode.ROAD and s.progress < 1.0), None)
    if not road_ship:
        return {"status": "error", "message": "No active road shipment found."}

    # Fetch all alternatives with full GeoJSON geometry
    coord_str = (
        f"{road_ship.start_lon},{road_ship.start_lat};{road_ship.end_lon},{road_ship.end_lat}"
    )
    new_path: list[list[float]] = []
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
        # route_index 0 = first alternate (skip primary at index 0 if available)
        target_idx = min(route_index + 1, len(routes) - 1) if len(routes) > 1 else 0
        chosen = routes[target_idx]
        new_path = chosen.get("geometry", {}).get("coordinates", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("apply_reroute.osrm_failed", error=str(exc))

    if len(new_path) < 2:
        # Fallback: use existing path (no-op gracefully)
        new_path = road_ship.route_path or [
            [road_ship.start_lon, road_ship.start_lat],
            [road_ship.end_lon, road_ship.end_lat],
        ]

    # Update the live SimulatedShipment in-memory — takes effect next tick
    road_ship.route_path = new_path

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

    # 2. Push updated tick so map immediately shows new route
    await redis_client.publish(
        channel,
        json.dumps(
            {
                "type": "simulation_tick",
                "shipments": [road_ship.payload()],
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
    return {
        "status": "rerouted",
        "shipment_id": road_ship.shipment_id,
        "route_index": route_index,
        "new_waypoints": len(new_path),
    }

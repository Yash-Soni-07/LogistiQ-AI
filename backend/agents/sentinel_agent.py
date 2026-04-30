"""
agents/sentinel_agent.py — Background monitoring agent for LogistiQ AI.

Phase 2 implementation:
  - score_all_routes(): every 15 minutes
  - scan_news_feeds(): every 30 minutes
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select, update

from agents.gdelt_scanner import scan_gdelt_news
from core.redis import redis_client
from db.database import AsyncSessionLocal
from db.models import RouteSegment
from ml.risk_scorer import MCPClient, RiskScore, compute_risk

log = structlog.get_logger(__name__)

# ── Mock Geocoder (Phase 2 interim) ──────────────────────────

KNOWN_LOCATIONS = {
    "mumbai": (19.076, 72.877),
    "delhi": (28.679, 77.213),
    "ahmedabad": (23.022, 72.571),
    "pune": (18.520, 73.856),
    "chennai": (13.082, 80.270),
    "kolkata": (22.572, 88.363),
    "hyderabad": (17.385, 78.486),
    "surat": (21.170, 72.831),
    "nagpur": (21.145, 79.082),
    "jaipur": (26.912, 75.787),
    "nh-48": (19.500, 73.200),
    "nh-44": (17.000, 78.000),
    "nh-27": (23.500, 72.000),
    "jnpt": (18.948, 72.951),
    "mundra": (22.839, 69.722),
}


def mock_geocode(location: str) -> tuple[float, float] | None:
    return KNOWN_LOCATIONS.get(location.lower().strip())


# ─────────────────────────────────────────────────────────────
# In-process MCP client adapter
# ─────────────────────────────────────────────────────────────


class InProcessMCPClient:
    """Calls a MCPServer instance directly without HTTP, satisfying MCPClient Protocol."""

    def __init__(self, server: Any) -> None:
        self._server = server

    async def call(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        result = await self._server.execute_tool(tool_name, params, tenant_id=None)
        if isinstance(result, dict):
            return result
        return {"result": result}


def _build_mcp_clients() -> dict[str, MCPClient]:
    """Build in-process MCP client dict for risk_scorer."""
    from mcp_servers.mcp_satellite import satellite_mcp
    from mcp_servers.mcp_weather import weather_mcp

    return {
        "weather": InProcessMCPClient(weather_mcp),  # type: ignore[arg-type]
        "satellite": InProcessMCPClient(satellite_mcp),  # type: ignore[arg-type]
    }


# ─────────────────────────────────────────────────────────────
# Sentinel Agent
# ─────────────────────────────────────────────────────────────


class SentinelAgent:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self.semaphore = asyncio.Semaphore(20)
        self.mcp_clients = _build_mcp_clients()

    async def start(self) -> None:
        """Start the scheduler and log segment count."""
        log.info("sentinel_agent.starting")
        self.scheduler.add_job(self.score_all_routes, "interval", minutes=15)
        self.scheduler.add_job(self.scan_news_feeds, "interval", minutes=30)
        self.scheduler.start()

        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(func.count(RouteSegment.id)))
                count = res.scalar() or 0
                log.info("sentinel_agent.started", active_segments=count)
        except Exception as exc:  # noqa: BLE001
            log.warning("sentinel_agent.startup_count_failed", error=str(exc))

    async def stop(self) -> None:
        """Graceful shutdown."""
        log.info("sentinel_agent.stopping")
        self.scheduler.shutdown()

    async def score_all_routes(self) -> None:
        t0 = asyncio.get_event_loop().time()

        # 1. Fetch all active route_segments
        async with AsyncSessionLocal() as db:
            query = select(
                RouteSegment.id,
                RouteSegment.highway_code,
                RouteSegment.risk_score.label("old_risk_score"),
                func.ST_Y(func.ST_Centroid(RouteSegment.geom)).label("lat"),
                func.ST_X(func.ST_Centroid(RouteSegment.geom)).label("lon"),
            ).where(RouteSegment.geom.is_not(None))

            result = await db.execute(query)
            segments = result.all()

        if not segments:
            log.info("sentinel.cycle.complete", segments_scored=0, events_fired=0, duration_s=0.0)
            return

        events_fired = 0
        updates = []

        # 2. Concurrently compute risk
        async def process_segment(seg: Any) -> tuple[Any, RiskScore]:
            async with self.semaphore:
                lat = float(seg.lat) if seg.lat is not None else 0.0
                lon = float(seg.lon) if seg.lon is not None else 0.0
                risk: RiskScore = await compute_risk(lat, lon, str(seg.id), self.mcp_clients)
                return seg, risk

        tasks = [process_segment(seg) for seg in segments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                log.error("sentinel.score_route.error", error=str(res))
                continue

            seg, risk = res
            new_risk = risk.risk_score
            old_risk = float(seg.old_risk_score) if seg.old_risk_score is not None else 0.0

            updates.append(
                {"id": seg.id, "risk_score": new_risk, "last_scored_at": datetime.now(tz=UTC)}
            )

            # 4. Fire events for crossing 0.75 threshold
            if new_risk > 0.75 and old_risk < 0.75:
                # determine dominant factor
                event_type = "unknown"
                if risk.rain_score > 0.6:
                    event_type = "flood"
                elif risk.fire_proximity_score > 0.6:
                    event_type = "fire"
                elif risk.strike_score > 0.6:
                    event_type = "strike"
                elif risk.quake_score > 0.6:
                    event_type = "quake"

                payload = {
                    "event_id": str(uuid.uuid4()),
                    "segment_id": str(seg.id),
                    "segment_name": seg.highway_code or "Unknown Segment",
                    "highway_code": seg.highway_code,
                    "risk_score": new_risk,
                    "previous_risk": old_risk,
                    "event_type": event_type,
                    "lat": float(seg.lat) if seg.lat is not None else 0.0,
                    "lon": float(seg.lon) if seg.lon is not None else 0.0,
                    "radius_km": 50.0,
                    "source_apis": risk.sources_used,
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                    "severity": "high" if new_risk < 0.85 else "critical",
                }

                await redis_client.publish("disruptions", json.dumps(payload))
                events_fired += 1

        # 3. Batch UPDATE route_segments
        if updates:
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(RouteSegment).execution_options(synchronize_session=None), updates
                    )
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                log.error("sentinel.batch_update.error", error=str(exc))

        duration_s = round(asyncio.get_event_loop().time() - t0, 2)
        log.info(
            "sentinel.cycle.complete",
            segments_scored=len(updates),
            events_fired=events_fired,
            duration_s=duration_s,
        )

    async def scan_news_feeds(self) -> None:
        log.info("sentinel.scan_news_feeds.start")
        try:
            alerts = await scan_gdelt_news()
        except Exception as exc:  # noqa: BLE001
            log.error("sentinel.scan_news_feeds.error", error=str(exc))
            return

        events_fired = 0
        async with AsyncSessionLocal() as db:
            for alert in alerts:
                # Handle both dict and object returns gracefully during transition
                if isinstance(alert, dict):
                    source_count = int(alert.get("source_count", 1))
                    location = alert.get("location", "")
                    alert_type = alert.get("alert_type", "unknown")
                    desc = alert.get("description", "")
                else:
                    source_count = int(getattr(alert, "source_count", 1))
                    location = getattr(alert, "location", "")
                    alert_type = getattr(alert, "alert_type", "unknown")
                    desc = getattr(alert, "description", "")

                if source_count >= 3:
                    coords = mock_geocode(location)
                    if coords:
                        lat, lon = coords
                        # ST_DWithin: 50km is ~0.45 degrees in EPSG:4326
                        query = select(RouteSegment.id).where(
                            func.ST_DWithin(
                                RouteSegment.geom,
                                func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
                                0.45,
                            )
                        )
                        res = await db.execute(query)
                        affected_segment_ids = [str(r[0]) for r in res.all()]

                        if affected_segment_ids:
                            payload = {
                                "event_id": str(uuid.uuid4()),
                                "affected_segment_ids": affected_segment_ids,
                                "event_type": "news_based",
                                "alert_type": alert_type,
                                "location": location,
                                "lat": lat,
                                "lon": lon,
                                "description": desc,
                                "source_count": source_count,
                                "timestamp": datetime.now(tz=UTC).isoformat(),
                            }
                            await redis_client.publish("disruptions", json.dumps(payload))
                            events_fired += 1

        log.info("sentinel.scan_news_feeds.complete", events_fired=events_fired)

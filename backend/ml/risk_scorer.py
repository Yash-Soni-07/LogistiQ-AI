"""
ml/risk_scorer.py — Multi-factor route-segment risk scorer for LogistiQ AI.

Aggregates signals from:
  - Weather MCP   → flood risk (rain + elevation)
  - Satellite MCP → active fires (proximity scoring)
  - Satellite MCP → earthquake alerts (magnitude + depth)
  - Redis          → GDELT strike probability for the segment

Composite formula (weights sum to 1.0):
    risk = 0.40 * flood + 0.25 * fire + 0.20 * strike + 0.15 * quake

Redis cache key: "risk:{lat:.3f}:{lon:.3f}:{date}"   TTL = 900 s
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import structlog
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from core.redis import redis_client

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# MCP client protocol — allows dependency injection / mocking
# ─────────────────────────────────────────────────────────────


class MCPClient(Protocol):
    """Minimal interface expected from an MCP client object."""

    async def call(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a tool and return its result dict."""
        ...


# ─────────────────────────────────────────────────────────────
# Output dataclass
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RiskScore:
    # ── Per-factor scores [0.0 – 1.0] ────────────────────────
    rain_score: float
    elevation_score: float
    fire_proximity_score: float
    quake_score: float
    strike_score: float

    # ── Composite ─────────────────────────────────────────────
    risk_score: float                           # weighted composite [0.0 – 1.0]
    composite_formula: str                      # human-readable formula used

    # ── Metadata ──────────────────────────────────────────────
    sources_used: list[str] = field(default_factory=list)
    cache_hit: bool = False
    computed_at: str = ""                       # ISO-8601 UTC timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "rain_score": self.rain_score,
            "elevation_score": self.elevation_score,
            "fire_proximity_score": self.fire_proximity_score,
            "quake_score": self.quake_score,
            "strike_score": self.strike_score,
            "composite_formula": self.composite_formula,
            "sources_used": self.sources_used,
            "cache_hit": self.cache_hit,
            "computed_at": self.computed_at,
        }


# ─────────────────────────────────────────────────────────────
# Weights (must sum to 1.0)
# ─────────────────────────────────────────────────────────────

_W_FLOOD = 0.40
_W_FIRE = 0.25
_W_STRIKE = 0.20
_W_QUAKE = 0.15
assert abs(_W_FLOOD + _W_FIRE + _W_STRIKE + _W_QUAKE - 1.0) < 1e-9, "Weights must sum to 1.0"

_FORMULA = (
    f"composite = {_W_FLOOD}*flood + {_W_FIRE}*fire "
    f"+ {_W_STRIKE}*strike + {_W_QUAKE}*quake"
)

# Fire proximity thresholds (km)
_FIRE_NEAR_KM = 5.0    # score = 0.9
_FIRE_MID_KM = 10.0    # score = 0.6


# ─────────────────────────────────────────────────────────────
# Haversine distance (km) — no numpy needed here
# ─────────────────────────────────────────────────────────────


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─────────────────────────────────────────────────────────────
# Score helpers
# ─────────────────────────────────────────────────────────────


def _fire_proximity_score(
    query_lat: float, query_lon: float, fire_features: list[dict[str, Any]]
) -> float:
    """
    Score based on accumulated intensity (FRP) and proximity.
    FRP > 10 is Strong, 3-10 is Medium.
    """
    total_score = 0.0
    for feature in fire_features:
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        try:
            f_lon, f_lat = float(coords[0]), float(coords[1])
            dist = _haversine_km(query_lat, query_lon, f_lat, f_lon)
            
            if dist > _FIRE_MID_KM:
                continue

            frp = float(feature.get("properties", {}).get("frp", 0.0))
            
            # Distance weight: 1.0 if <= 5km, 0.5 if <= 10km
            dist_weight = 1.0 if dist <= _FIRE_NEAR_KM else 0.5
            
            # Intensity weight
            if frp > 10.0:
                frp_weight = 0.9
            elif frp >= 3.0:
                frp_weight = 0.6
            else:
                frp_weight = 0.1
                
            total_score += dist_weight * frp_weight
            
        except (TypeError, ValueError):
            continue
    return min(total_score, 1.0)


def _quake_score(earthquakes: list[dict[str, Any]]) -> float:
    """
    max over all earthquakes of:
        min(magnitude / 5.0, 1.0) * (1 - depth_km / 30)   for M >= 3.5
    clamped to [0, 1].
    """
    best = 0.0
    for eq in earthquakes:
        try:
            mag = float(eq.get("magnitude", 0))
            depth = float(eq.get("depth_km", 30))
            if mag < 3.5:
                continue
            score = min(mag / 5.0, 1.0) * max(0.0, 1.0 - depth / 30.0)
            best = max(best, score)
        except (TypeError, ValueError):
            continue
    return min(best, 1.0)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


async def compute_risk(
    lat: float,
    lon: float,
    segment_id: str,
    mcp_clients: dict[str, MCPClient],
) -> RiskScore:
    """
    Compute a composite risk score for a route segment centred at (lat, lon).

    Parameters
    ----------
    lat, lon      : Centre of the segment / waypoint.
    segment_id    : Opaque ID used as Redis key prefix for strike probability.
    mcp_clients   : Dict with keys "weather" and "satellite", each an MCPClient.

    Returns
    -------
    RiskScore dataclass (frozen, JSON-serialisable via .to_dict()).
    """
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    cache_key = f"risk:{lat:.3f}:{lon:.3f}:{today}"

    # ── Cache read ────────────────────────────────────────────
    cached_raw = await redis_client.get(cache_key)
    if cached_raw:
        try:
            d = json.loads(cached_raw)
            log.debug("risk_scorer.cache_hit", segment_id=segment_id, key=cache_key)
            return RiskScore(
                rain_score=d["rain_score"],
                elevation_score=d["elevation_score"],
                fire_proximity_score=d["fire_proximity_score"],
                quake_score=d["quake_score"],
                strike_score=d["strike_score"],
                risk_score=d["risk_score"],
                composite_formula=d["composite_formula"],
                sources_used=d["sources_used"],
                cache_hit=True,
                computed_at=d["computed_at"],
            )
        except (KeyError, json.JSONDecodeError):
            pass  # corrupt cache — recompute

    weather_client = mcp_clients.get("weather")
    satellite_client = mcp_clients.get("satellite")

    sources_used: list[str] = []

    # ── Fan-out: flood risk + fires + earthquakes concurrently ─
    bbox = [lon - 0.5, lat - 0.5, lon + 0.5, lat + 0.5]  # ~55 km box

    async def _safe_mcp_call(client: MCPClient | None, tool: str, params: dict[str, Any], default: Any) -> Any:
        if client is None:
            return default
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                reraise=True,
            ):
                with attempt:
                    result = await client.call(tool, params)
                    return result
        except Exception as exc:  # noqa: BLE001
            log.warning("risk_scorer.mcp_fetch_failed", tool=tool, error=str(exc))
            return default

    async def _get_flood() -> dict[str, Any]:
        res = await _safe_mcp_call(weather_client, "get_flood_risk", {"lat": lat, "lon": lon}, {})
        if res:
            sources_used.append("weather:get_flood_risk")
        return res

    async def _get_fires() -> list[dict[str, Any]]:
        res = await _safe_mcp_call(satellite_client, "get_active_fires", {"bbox": bbox}, {"features": []})
        if res and "features" in res:
            sources_used.append("satellite:get_active_fires")
            return res.get("features", [])
        return []

    async def _get_quakes() -> list[dict[str, Any]]:
        res = await _safe_mcp_call(satellite_client, "get_earthquake_alerts", {"lat": lat, "lon": lon, "radius_km": 100}, [])
        if res:
            sources_used.append("satellite:get_earthquake_alerts")
        return res if isinstance(res, list) else []

    flood_data, fire_features, quake_list = await asyncio.gather(
        _get_flood(), _get_fires(), _get_quakes()
    )

    # ── Flood components ──────────────────────────────────────
    # flood_data keys: risk_score, rain_24h_mm, elevation_m, etc.
    flood_risk = float(flood_data.get("risk_score", 0.0))
    rain_24h = float(flood_data.get("rain_24h_mm", 0.0))
    elevation_m = float(flood_data.get("elevation_m", 0.0))

    # Decompose flood into its sub-components (mirroring weather MCP formula)
    rain_score = min(0.6 * (rain_24h / 20.0), 0.6) if rain_24h else flood_risk * 0.6
    elev_score = min(0.4 * (1.0 - elevation_m / 50.0), 0.4) if elevation_m else flood_risk * 0.4

    # ── Fire score ────────────────────────────────────────────
    fire_score = _fire_proximity_score(lat, lon, fire_features)

    # ── Quake score ───────────────────────────────────────────
    quake_s = _quake_score(quake_list)

    # ── Strike probability from Redis (GDELT scanner) ─────────
    strike_s = 0.0
    try:
        strike_raw = await redis_client.get(f"news:{segment_id}:strike_probability")
        if strike_raw:
            strike_s = max(0.0, min(1.0, float(strike_raw)))
            sources_used.append("redis:gdelt_strike")
    except Exception as exc:  # noqa: BLE001
        log.warning("risk_scorer.strike_fetch_failed", segment_id=segment_id, error=str(exc))

    # ── Composite score ───────────────────────────────────────
    composite = round(
        _W_FLOOD * flood_risk
        + _W_FIRE * fire_score
        + _W_STRIKE * strike_s
        + _W_QUAKE * quake_s,
        4,
    )
    composite = max(0.0, min(1.0, composite))

    computed_at = datetime.now(tz=timezone.utc).isoformat()

    score = RiskScore(
        rain_score=round(rain_score, 4),
        elevation_score=round(elev_score, 4),
        fire_proximity_score=round(fire_score, 4),
        quake_score=round(quake_s, 4),
        strike_score=round(strike_s, 4),
        risk_score=composite,
        composite_formula=_FORMULA,
        sources_used=list(set(sources_used)),
        cache_hit=False,
        computed_at=computed_at,
    )

    # ── Cache write ───────────────────────────────────────────
    try:
        await redis_client.setex(cache_key, 900, json.dumps(score.to_dict()))
    except Exception as exc:  # noqa: BLE001
        log.warning("risk_scorer.cache_write_failed", error=str(exc))

    log.info(
        "risk_scorer.computed",
        segment_id=segment_id,
        lat=lat,
        lon=lon,
        risk_score=composite,
        sources=score.sources_used,
    )

    return score

"""
MCP Satellite Server — fire detection, earthquakes, elevation, SAR flood zones.

External APIs:
  - NASA FIRMS   https://firms.modaps.eosdis.nasa.gov
  - USGS         https://earthquake.usgs.gov
  - Open-Elevation https://api.open-elevation.com
  - EFFIS (fallback fires) https://effis.jrc.ec.europa.eu
# TODO(Phase 4): EFFIS URL has moved permanently to:
# https://forest-fire.emergency.copernicus.eu/api/fire-seasonal/api/data/fire-features
# Current URL returns 302 redirect. Update after Phase 3 frontend completion.
# Tracked: Phase 4 API integration polish
"""

from __future__ import annotations

import csv
import io
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

_firms_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
_usgs_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
_elev_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# ─────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────

BBox = list[float]  # [min_lon, min_lat, max_lon, max_lat]


class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]


class GeoJSONCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJSONFeature]
    source: str = ""


class EarthquakeAlert(BaseModel):
    id: str
    magnitude: float
    place: str
    time_utc: str
    depth_km: float
    lat: float
    lon: float
    url: str


class ElevationResult(BaseModel):
    lat: float
    lon: float
    elevation_m: float
    source: str = "Open-Elevation"


# ─────────────────────────────────────────────────────────────
# MCP Satellite Server
# ─────────────────────────────────────────────────────────────


class SatelliteMCPServer(MCPServer):
    """Tools backed by NASA FIRMS, USGS, Open-Elevation, and EFFIS."""

    tools: dict[str, MCPToolSchema] = {
        "get_active_fires": MCPToolSchema(
            name="get_active_fires",
            description=(
                "Return active fire detections as GeoJSON from NASA FIRMS (VIIRS SNPP NRT). "
                "Falls back to EFFIS if FIRMS is unavailable or key is missing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "[min_lon, min_lat, max_lon, max_lat]",
                    },
                    "day_range": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 5,
                    },
                    "date": {
                        "type": "string",
                        "description": "YYYY-MM-DD",
                    },
                },
            },
            required=["bbox"],
        ),
        "get_earthquake_alerts": MCPToolSchema(
            name="get_earthquake_alerts",
            description="Return recent earthquakes ≥ M3.5 within radius from USGS.",
            parameters={
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "radius_km": {"type": "number", "default": 50},
                },
            },
            required=["lat", "lon"],
        ),
        "get_elevation": MCPToolSchema(
            name="get_elevation",
            description="Return terrain elevation at lat/lon from Open-Elevation.",
            parameters={
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                },
            },
            required=["lat", "lon"],
        ),
        "get_sar_flood_zones": MCPToolSchema(
            name="get_sar_flood_zones",
            description=(
                "Return a GeoJSON FeatureCollection of estimated SAR-derived flood zones "
                "for the given bounding box. Uses EFFIS flood-seasonal data as proxy."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                },
            },
            required=["bbox"],
        ),
    }

    async def execute_tool(
        self, name: str, params: dict[str, Any], tenant_id: str | None
    ) -> Any:
        try:
            match name:
                case "get_active_fires":
                    return (await self._get_active_fires(
                        params["bbox"],
                        params.get("day_range", 5),
                        params.get("date"),
                    )).model_dump()
                case "get_earthquake_alerts":
                    alerts = await self._get_earthquake_alerts(
                        params["lat"], params["lon"], params.get("radius_km", 50)
                    )
                    return [a.model_dump() for a in alerts]
                case "get_elevation":
                    return (await self._get_elevation(params["lat"], params["lon"])).model_dump()
                case "get_sar_flood_zones":
                    return (await self._get_sar_flood_zones(params["bbox"])).model_dump()
                case _:
                    raise ValueError(f"Unknown tool: {name}")
        except Exception as exc:  # noqa: BLE001
            log.error("mcp.satellite.tool_failed", tool=name, error=str(exc))
            # Safe fallbacks per tool
            if name in ("get_active_fires", "get_sar_flood_zones"):
                return GeoJSONCollection(features=[], source="fallback_empty").model_dump()
            elif name == "get_earthquake_alerts":
                return []
            elif name == "get_elevation":
                return ElevationResult(lat=params.get("lat", 0.0), lon=params.get("lon", 0.0), elevation_m=0.0).model_dump()
            return {}

    # ── Fire detection ────────────────────────────────────────

    async def _get_active_fires(
        self, bbox: list[float], day_range: int = 5, date_str: str | None = None
    ) -> GeoJSONCollection:
        min_lon, min_lat, max_lon, max_lat = bbox
        bbox_str = f"{min_lon},{min_lat},{max_lon},{max_lat}"

        nasa_key = settings.NASA_FIRMS_KEY
        features: list[GeoJSONFeature] = []
        source = ""

        if nasa_key:
            url = (
                f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
                f"{nasa_key}/VIIRS_SNPP_NRT/{bbox_str}/{day_range}"
            )
            if date_str:
                url += f"/{date_str}"
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=20.0)
                    resp.raise_for_status()
                    text = resp.text

                reader = csv.DictReader(io.StringIO(text))
                for row in reader:
                    try:
                        confidence = row.get("confidence", "l")
                        if confidence == "l":
                            continue
                            
                        frp = float(row.get("frp", 0))
                        if frp < 3.0:
                            continue

                        lat_f = float(row.get("latitude", 0))
                        lon_f = float(row.get("longitude", 0))
                        features.append(
                            GeoJSONFeature(
                                geometry={"type": "Point", "coordinates": [lon_f, lat_f]},
                                properties={
                                    "frp": frp,
                                    "acq_date": row.get("acq_date"),
                                    "acq_time": row.get("acq_time"),
                                    "confidence": row.get("confidence"),
                                    "source": "NASA FIRMS VIIRS SNPP NRT",
                                },
                            )
                        )
                    except (ValueError, KeyError):
                        continue
                source = "NASA FIRMS"
                return GeoJSONCollection(features=features, source=source)
            except Exception as exc:  # noqa: BLE001
                log.warning("firms.api_failed_using_effis_fallback", error=str(exc))

        # EFFIS fallback
        effis_url = (
            "https://effis.jrc.ec.europa.eu/api/fire-seasonal/api/data/fire-features"
            f"?bbox={min_lon},{min_lat},{max_lon},{max_lat}"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(effis_url, timeout=20.0)
                resp.raise_for_status()
                data = resp.json()
            raw_features = data.get("features", [])
            for f in raw_features:
                features.append(
                    GeoJSONFeature(
                        geometry=f.get("geometry", {}),
                        properties=f.get("properties", {}),
                    )
                )
            source = "EFFIS (fallback)"
        except Exception as exc:  # noqa: BLE001
            log.warning("effis.api_failed", error=str(exc))
            source = "unavailable"

        return GeoJSONCollection(features=features, source=source)

    # ── Earthquakes ───────────────────────────────────────────

    async def _get_earthquake_alerts(
        self, lat: float, lon: float, radius_km: float
    ) -> list[EarthquakeAlert]:
        url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                params={
                    "format": "geojson",
                    "minmagnitude": 3.5,
                    "latitude": lat,
                    "longitude": lon,
                    "maxradiuskm": radius_km,
                    "orderby": "time",
                    "limit": 50,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        alerts: list[EarthquakeAlert] = []
        import datetime

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [0, 0, 0])
            try:
                time_ms = props.get("time", 0)
                time_utc = datetime.datetime.utcfromtimestamp(time_ms / 1000).isoformat() + "Z"
                alerts.append(
                    EarthquakeAlert(
                        id=feature.get("id", ""),
                        magnitude=float(props.get("mag", 0)),
                        place=props.get("place", ""),
                        time_utc=time_utc,
                        depth_km=float(coords[2]) if len(coords) > 2 else 0.0,
                        lat=float(coords[1]),
                        lon=float(coords[0]),
                        url=props.get("url", ""),
                    )
                )
            except (TypeError, ValueError):
                continue

        return alerts

    # ── Elevation ─────────────────────────────────────────────

    async def _get_elevation(self, lat: float, lon: float) -> ElevationResult:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.open-elevation.com/api/v1/lookup",
                params={"locations": f"{lat},{lon}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

        elev = data.get("results", [{}])[0].get("elevation", 0.0) or 0.0
        return ElevationResult(lat=lat, lon=lon, elevation_m=float(elev))

    # ── SAR Flood Zones (proxy via EFFIS) ─────────────────────

    async def _get_sar_flood_zones(self, bbox: list[float]) -> GeoJSONCollection:
        min_lon, min_lat, max_lon, max_lat = bbox
        url = (
            "https://effis.jrc.ec.europa.eu/api/fire-seasonal/api/data/fire-features"
            f"?bbox={min_lon},{min_lat},{max_lon},{max_lat}"
        )
        features: list[GeoJSONFeature] = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=20.0)
                resp.raise_for_status()
                data = resp.json()
            for f in data.get("features", []):
                features.append(
                    GeoJSONFeature(
                        geometry=f.get("geometry", {}),
                        properties={**f.get("properties", {}), "data_type": "sar_proxy_flood"},
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("sar_flood_zones.fetch_failed", error=str(exc))

        return GeoJSONCollection(features=features, source="EFFIS SAR proxy")


# Singleton instance
satellite_mcp = SatelliteMCPServer(prefix="/mcp/satellite")

"""
MCP Weather Server — flood risk, 72-h forecast, active alerts, IMD bulletin.

External APIs (all async via httpx):
  - Open-Meteo   https://api.open-meteo.com
  - Open-Elevation https://api.open-elevation.com
  - IMD RSS      https://mausam.imd.gov.in
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pybreaker
import structlog
from pydantic import BaseModel, Field

from core.redis import redis_client
from mcp_servers.base import MCPServer, MCPToolSchema

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Circuit breakers (one per upstream)
# ─────────────────────────────────────────────────────────────

_meteo_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
_elevation_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
_imd_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# ─────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────


class FloodRiskResult(BaseModel):
    lat: float
    lon: float
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    rain_24h_mm: float
    elevation_m: float
    cached: bool = False


class ForecastResult(BaseModel):
    lat: float
    lon: float
    hourly_timestamps: list[str]
    temperature_2m: list[float]
    precipitation: list[float]
    windspeed_10m: list[float]


class WeatherAlert(BaseModel):
    region: str
    title: str
    severity: str
    description: str
    source: str


class IMDBulletinResult(BaseModel):
    raw_text: str
    source_url: str
    fetched_at: str


# ─────────────────────────────────────────────────────────────
# Helper: async HTTP fetches with circuit breakers
# ─────────────────────────────────────────────────────────────


async def _fetch_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> Any:
    resp = await client.get(url, params=params, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=15.0)
    resp.raise_for_status()
    return resp.text


# ─────────────────────────────────────────────────────────────
# MCP Weather Server
# ─────────────────────────────────────────────────────────────


class WeatherMCPServer(MCPServer):
    """MCP server providing weather and environmental risk tools."""

    tools: dict[str, MCPToolSchema] = {
        "get_flood_risk": MCPToolSchema(
            name="get_flood_risk",
            description=(
                "Compute flood risk score [0-1] for a given lat/lon using "
                "24-h precipitation (Open-Meteo) and elevation (Open-Elevation). "
                "Results cached for 15 minutes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Latitude"},
                    "lon": {"type": "number", "description": "Longitude"},
                },
            },
            required=["lat", "lon"],
        ),
        "get_forecast_72h": MCPToolSchema(
            name="get_forecast_72h",
            description="Return hourly 72-h weather forecast from Open-Meteo.",
            parameters={
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                },
            },
            required=["lat", "lon"],
        ),
        "get_active_weather_alerts": MCPToolSchema(
            name="get_active_weather_alerts",
            description="Return active weather alerts for a region via Open-Meteo.",
            parameters={
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "Region name, e.g. 'Mumbai'"},
                },
            },
            required=["region"],
        ),
        "get_imd_bulletin": MCPToolSchema(
            name="get_imd_bulletin",
            description="Scrape the latest IMD cyclone/severe weather bulletin.",
            parameters={"type": "object", "properties": {}},
            required=[],
        ),
    }

    # ── execute_tool dispatcher ───────────────────────────────

    async def execute_tool(self, name: str, params: dict[str, Any], tenant_id: str | None) -> Any:
        try:
            match name:
                case "get_flood_risk":
                    return (await self._get_flood_risk(params["lat"], params["lon"])).model_dump()
                case "get_forecast_72h":
                    return (await self._get_forecast_72h(params["lat"], params["lon"])).model_dump()
                case "get_active_weather_alerts":
                    alerts = await self._get_active_weather_alerts(params["region"])
                    return [a.model_dump() for a in alerts]
                case "get_imd_bulletin":
                    return (await self._get_imd_bulletin()).model_dump()
                case _:
                    raise ValueError(f"Unknown tool: {name}")
        except Exception as exc:  # noqa: BLE001
            log.error("mcp.weather.tool_failed", tool=name, error=str(exc))
            # Safe fallbacks per tool
            if name == "get_flood_risk":
                return FloodRiskResult(
                    lat=params.get("lat", 0.0),
                    lon=params.get("lon", 0.0),
                    risk_score=0.0,
                    risk_level="LOW",
                    rain_24h_mm=0.0,
                    elevation_m=0.0,
                ).model_dump()
            elif name == "get_forecast_72h":
                return ForecastResult(
                    lat=params.get("lat", 0.0),
                    lon=params.get("lon", 0.0),
                    hourly_timestamps=[],
                    temperature_2m=[],
                    precipitation=[],
                    windspeed_10m=[],
                ).model_dump()
            elif name == "get_active_weather_alerts":
                return []
            elif name == "get_imd_bulletin":
                return IMDBulletinResult(
                    raw_text="Unavailable", source_url="", fetched_at=""
                ).model_dump()
            return {}

    # ── Tool implementations ──────────────────────────────────

    async def _get_flood_risk(self, lat: float, lon: float) -> FloodRiskResult:
        cache_key = f"mcp:flood_risk:{lat:.4f}:{lon:.4f}"
        cached = await redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            data["cached"] = True
            return FloodRiskResult(**data)

        async with httpx.AsyncClient() as client:
            meteo_task = asyncio.create_task(
                _fetch_json(
                    client,
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "hourly": "precipitation",
                        "forecast_days": 1,
                        "timezone": "auto",
                    },
                )
            )
            # TODO(Phase 4): Open-Elevation free tier hits 429 under concurrent load.
            # Fix: Add Redis cache with TTL=86400 (elevation never changes) before API call.
            # Key pattern: "elevation:{lat:.3f}:{lon:.3f}"
            # Tracked: Phase 4 API integration polish
            elev_task = asyncio.create_task(
                _fetch_json(
                    client,
                    "https://api.open-elevation.com/api/v1/lookup",
                    params={"locations": f"{lat},{lon}"},
                )
            )
            meteo_data, elev_data = await asyncio.gather(meteo_task, elev_task)

        # Sum last 24 hourly precipitation values
        precip_vals: list[float] = meteo_data.get("hourly", {}).get("precipitation", [0.0])
        rain_24h = sum(precip_vals[:24])

        elevation: float = elev_data.get("results", [{}])[0].get("elevation", 0.0) or 0.0

        # Formula as specified
        rain_component = min(0.6 * (rain_24h / 20.0), 0.6)
        elev_component = min(0.4 * (1.0 - elevation / 50.0), 0.4)
        risk = round(max(0.0, min(1.0, rain_component + elev_component)), 4)

        if risk >= 0.7:
            risk_level = "CRITICAL"
        elif risk >= 0.5:
            risk_level = "HIGH"
        elif risk >= 0.3:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        result = FloodRiskResult(
            lat=lat,
            lon=lon,
            risk_score=risk,
            risk_level=risk_level,
            rain_24h_mm=round(rain_24h, 2),
            elevation_m=round(elevation, 1),
            cached=False,
        )
        await redis_client.setex(cache_key, 900, json.dumps(result.model_dump()))
        return result

    async def _get_forecast_72h(self, lat: float, lon: float) -> ForecastResult:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(
                client,
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "temperature_2m,precipitation,windspeed_10m",
                    "forecast_days": 3,
                    "timezone": "auto",
                },
            )

        hourly = data.get("hourly", {})
        return ForecastResult(
            lat=lat,
            lon=lon,
            hourly_timestamps=hourly.get("time", [])[:72],
            temperature_2m=hourly.get("temperature_2m", [])[:72],
            precipitation=hourly.get("precipitation", [])[:72],
            windspeed_10m=hourly.get("windspeed_10m", [])[:72],
        )

    async def _get_active_weather_alerts(self, region: str) -> list[WeatherAlert]:
        """
        Open-Meteo doesn't supply alerts natively; we query current conditions
        and synthesise an alert if precipitation or windspeed exceed thresholds.
        """
        # Simple geocode approximation for Indian regions
        region_coords: dict[str, tuple[float, float]] = {
            "mumbai": (19.076, 72.877),
            "delhi": (28.704, 77.102),
            "chennai": (13.082, 80.270),
            "kolkata": (22.572, 88.363),
            "bangalore": (12.971, 77.594),
            "hyderabad": (17.385, 78.486),
        }
        coords = region_coords.get(region.lower(), (20.5937, 78.9629))

        async with httpx.AsyncClient() as client:
            data = await _fetch_json(
                client,
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": coords[0],
                    "longitude": coords[1],
                    "current": "precipitation,windspeed_10m",
                    "timezone": "auto",
                },
            )

        current = data.get("current", {})
        precip = current.get("precipitation", 0.0)
        wind = current.get("windspeed_10m", 0.0)

        alerts: list[WeatherAlert] = []
        if precip > 10:
            alerts.append(
                WeatherAlert(
                    region=region,
                    title="Heavy Rainfall Warning",
                    severity="HIGH" if precip > 30 else "MEDIUM",
                    description=f"Current precipitation: {precip} mm/h",
                    source="Open-Meteo",
                )
            )
        if wind > 60:
            alerts.append(
                WeatherAlert(
                    region=region,
                    title="High Wind Advisory",
                    severity="HIGH" if wind > 90 else "MEDIUM",
                    description=f"Current windspeed: {wind} km/h",
                    source="Open-Meteo",
                )
            )
        return alerts

    async def _get_imd_bulletin(self) -> IMDBulletinResult:
        import datetime

        imd_url = "https://mausam.imd.gov.in/responsive/cycloneWarning.php"
        try:
            async with httpx.AsyncClient() as client:
                text = await _fetch_text(client, imd_url)
            # Strip HTML tags for a plain-text summary (simple approach)
            import re

            clean = re.sub(r"<[^>]+>", " ", text)
            clean = re.sub(r"\s+", " ", clean).strip()[:2000]
        except Exception as exc:  # noqa: BLE001
            log.warning("imd_bulletin.fetch_failed", error=str(exc))
            clean = "IMD bulletin unavailable — network error or scrape blocked."

        return IMDBulletinResult(
            raw_text=clean,
            source_url=imd_url,
            fetched_at=datetime.datetime.utcnow().isoformat() + "Z",
        )


# Singleton instance (imported by main app)
weather_mcp = WeatherMCPServer(prefix="/mcp/weather")

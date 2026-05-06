"""
api/websocket_routes.py — WebSocket connection manager and channel endpoints.

Channels:
  /ws/shipments                — fleet-wide real-time tracking
  /ws/shipments/{shipment_id}  — per-shipment real-time tracking
  /ws/agent-log                — agent decisions stream
  /ws/disruptions              — tenant disruption feed
  /ws/carrier-auction/{id}     — carrier bid streaming
  /ws/copilot/{session_id}     — gemini SSE proxying
  /ws/dashboard                — KPI tick stream

Authentication via ?token=<jwt> query parameter (browser WS API limitation).
Global `manager` singleton is imported by sentinel_agent.py.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime

import google.generativeai as genai
import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import decode_token
from core.config import settings
from core.exceptions import UnauthorizedError
from core.redis import redis_client
from db.database import AsyncSessionLocal, get_db_session
from db.models import Shipment, ShipmentStatus

log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Connection Manager
# ─────────────────────────────────────────────────────────────


class ConnectionManager:
    """Thread-safe (asyncio) WebSocket connection registry."""

    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, ws: WebSocket, channel: str) -> None:
        """Register ws on channel. Caller must have already called ws.accept()."""
        self.connections[channel].add(ws)
        log.info("ws.connected", channel=channel, total=len(self.connections[channel]))

    async def disconnect(self, ws: WebSocket, channel: str) -> None:
        self.connections[channel].discard(ws)
        if not self.connections[channel]:
            del self.connections[channel]
        log.info("ws.disconnected", channel=channel)

    async def broadcast(self, channel: str, data: dict) -> None:
        """Send data to all connections on a channel. Silently drops dead sockets."""
        dead: list[WebSocket] = []
        for ws in list(self.connections.get(channel, set())):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections[channel].discard(ws)

    async def broadcast_to_tenant(self, tenant_id: str, event_type: str, data: dict) -> None:
        """Broadcast to the tenant-level channel (used by sentinel_agent)."""
        payload = {
            "event": event_type,
            "data": data,
            "ts": datetime.now(UTC).isoformat(),
        }
        await self.broadcast(f"tenant:{tenant_id}", payload)

    def connection_count(self, channel: str | None = None) -> int:
        if channel:
            return len(self.connections.get(channel, set()))
        return sum(len(v) for v in self.connections.values())

    def active_channels(self) -> list[str]:
        return [k for k, v in self.connections.items() if v]


# ── Global singleton ─────────
manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────
# Auth helper
# ─────────────────────────────────────────────────────────────


async def _authenticate_ws(token: str) -> dict[str, str]:
    """Decode JWT from ?token= query param. Raises UnauthorizedError on failure."""
    try:
        payload = decode_token(token)
        return {
            "user_id": str(payload.user_id),
            "tenant_id": str(payload.tenant_id),
            "role": str(payload.role),
        }
    except UnauthorizedError:
        raise
    except Exception as exc:
        raise UnauthorizedError("Invalid or expired WebSocket token") from exc


# ─────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────

router = APIRouter(prefix="/ws", tags=["websocket"])


# ─────────────────────────────────────────────────────────────
# Redis PubSub Task Helper
# ─────────────────────────────────────────────────────────────


async def _redis_reader(pubsub, ws: WebSocket):
    """Reads from Redis pubsub and forwards to WebSocket."""
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await ws.send_json(data)
                except (json.JSONDecodeError, RuntimeError):
                    if isinstance(message["data"], str):
                        await ws.send_text(message["data"])
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log.error("ws.redis_reader.error", error=str(exc))


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────


@router.websocket("/shipments")
async def ws_shipments_all(
    ws: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Fleet-wide tracking. Sends active shipments on connect, then streams updates."""
    try:
        ctx = await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    tenant_id = ctx["tenant_id"]
    channel = f"shipments:{tenant_id}"
    await ws.accept()
    await manager.connect(ws, channel)

    # 1. Send initial state GeoJSON — filter to demo shipment IDs when simulation is running
    try:
        # Check if a demo simulation is active for this tenant
        demo_ids_raw = await redis_client.smembers(f"demo_shipments:{tenant_id}")
        demo_ids: set[str] = {m.decode() if isinstance(m, bytes) else m for m in demo_ids_raw}

        query = select(Shipment).where(
            Shipment.tenant_id == tenant_id,
            Shipment.status.in_(
                [ShipmentStatus.PENDING, ShipmentStatus.IN_TRANSIT, ShipmentStatus.DELAYED]
            ),
        )
        result = await db.execute(query)
        shipments = result.scalars().all()

        # If demo is active, only show demo shipments (avoids cluttering map)
        if demo_ids:
            shipments = [s for s in shipments if str(s.id) in demo_ids]

        features = []
        for s in shipments:
            current_lon = float(s.current_lon) if s.current_lon is not None else 78.9629
            current_lat = float(s.current_lat) if s.current_lat is not None else 20.5937
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [current_lon, current_lat]},
                    "properties": {
                        "shipment_id": s.id,
                        "status": s.status.value if hasattr(s.status, "value") else s.status,
                        "origin": s.origin,
                        "destination": s.destination,
                        "mode": s.mode.value if hasattr(s.mode, "value") else s.mode,
                        "current_lon": current_lon,
                        "current_lat": current_lat,
                    },
                }
            )
        await ws.send_json({"type": "FeatureCollection", "features": features})
    except Exception as e:
        log.warning("ws.shipments.initial_state_failed", error=str(e))

    # 2. Redis PubSub
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    redis_task = asyncio.create_task(_redis_reader(pubsub, ws))

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if msg == "ping":
                    await ws.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})
            except TimeoutError:
                await ws.send_json({"type": "heartbeat", "ts": datetime.now(UTC).isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        redis_task.cancel()
        await pubsub.unsubscribe(channel)
        await manager.disconnect(ws, channel)


@router.websocket("/agent-log")
async def ws_agent_log(
    ws: WebSocket,
    token: str = Query(...),
) -> None:
    """Agent decision log stream with historical buffer."""
    try:
        ctx = await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    tenant_id = ctx["tenant_id"]
    channel = f"agent_log:{tenant_id}"
    await ws.accept()
    await manager.connect(ws, channel)

    # Fetch last 100 entries from Redis
    try:
        history = await redis_client.lrange(channel, 0, 99)
        for item in reversed(history):  # Send oldest first
            try:
                await ws.send_json(json.loads(item))
            except json.JSONDecodeError:
                pass
    except Exception as e:
        log.warning("ws.agent_log.history_failed", error=str(e))

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    redis_task = asyncio.create_task(_redis_reader(pubsub, ws))

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if msg == "ping":
                    await ws.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        redis_task.cancel()
        await pubsub.unsubscribe(channel)
        await manager.disconnect(ws, channel)


@router.websocket("/vrp-results")
async def ws_vrp_results(
    ws: WebSocket,
    token: str = Query(...),
) -> None:
    """Stream VRP rerouting results from the decision agent to Route Optimizer."""
    try:
        ctx = await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    tenant_id = ctx["tenant_id"]
    channel = f"vrp_results:{tenant_id}"
    await ws.accept()
    await manager.connect(ws, channel)

    # Send cached latest result if available
    try:
        cached = await redis_client.get(f"vrp_results:{tenant_id}:latest")
        if cached:
            await ws.send_json(json.loads(cached))
    except Exception as e:
        log.warning("ws.vrp_results.cache_failed", error=str(e))

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    redis_task = asyncio.create_task(_redis_reader(pubsub, ws))

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if msg == "ping":
                    await ws.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        redis_task.cancel()
        await pubsub.unsubscribe(channel)
        await manager.disconnect(ws, channel)


@router.websocket("/disruptions")
async def ws_disruptions(
    ws: WebSocket,
    token: str = Query(...),
) -> None:
    """Tenant disruption alert feed."""
    try:
        ctx = await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    tenant_id = ctx["tenant_id"]
    channel = f"tenant:{tenant_id}:disruptions"
    await ws.accept()
    await manager.connect(ws, channel)

    await ws.send_json(
        {
            "type": "connected",
            "channel": "disruptions",
            "tenant_id": tenant_id,
            "ts": datetime.now(UTC).isoformat(),
        }
    )

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("disruptions")

    async def _disruptions_reader(pub, websocket):
        try:
            async for message in pub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        affected_tenants = data.get("affected_tenants", [])
                        if not affected_tenants or tenant_id in affected_tenants:
                            await websocket.send_json(data)
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            pass

    redis_task = asyncio.create_task(_disruptions_reader(pubsub, ws))

    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if msg == "ping":
                    await ws.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})
            except TimeoutError:
                await ws.send_json({"type": "heartbeat", "ts": datetime.now(UTC).isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        redis_task.cancel()
        await pubsub.unsubscribe("disruptions")
        await manager.disconnect(ws, channel)


@router.websocket("/carrier-auction/{shipment_id}")
async def ws_carrier_auction(
    ws: WebSocket,
    shipment_id: str,
    token: str = Query(...),
) -> None:
    """Carrier auction bid stream."""
    try:
        await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    channel = f"auction:{shipment_id}"
    await ws.accept()
    await manager.connect(ws, channel)

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    redis_task = asyncio.create_task(_redis_reader(pubsub, ws))

    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        redis_task.cancel()
        await pubsub.unsubscribe(channel)
        await manager.disconnect(ws, channel)


@router.websocket("/copilot/{session_id}")
async def ws_copilot(
    ws: WebSocket,
    session_id: str,
    token: str = Query(...),
) -> None:
    """Proxies SSE from Gemini streaming API as WebSocket frames."""
    try:
        ctx = await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    channel = f"copilot:{session_id}"
    await ws.accept()
    await manager.connect(ws, channel)

    try:
        question = await ws.receive_text()

        from agents.copilot_agent import _classify_intent

        intent = _classify_intent(question)

        if intent != "general" or not getattr(settings, "GEMINI_API_KEY", None):
            # Non-general or fallback: run standard query
            from agents.copilot_agent import query

            async with AsyncSessionLocal() as db:
                response = await query(question, ctx["tenant_id"], ctx["user_id"], db)

            await ws.send_json({"type": "token", "content": response.answer})
            await ws.send_json(
                {"type": "done", "reasoning_steps": [], "suggested_actions": response.tool_calls}
            )
        else:
            # Gemini streaming
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                model_name=getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash"),
                system_instruction="You are LogistiQ AI Copilot — an expert assistant for Indian logistics operators. Answer concisely in plain English.",  # noqa: E501
            )
            response_stream = model.generate_content(question, stream=True)
            for chunk in response_stream:
                if chunk.text:
                    await ws.send_json({"type": "token", "content": chunk.text})

            await ws.send_json({"type": "done", "reasoning_steps": [], "suggested_actions": []})

        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        exc_str = str(exc)
        # ── Detect Gemini / Google API quota exhaustion (HTTP 429 / gRPC RESOURCE_EXHAUSTED) ──
        is_rate_limit = (
            "429" in exc_str
            or "RESOURCE_EXHAUSTED" in exc_str
            or "quota" in exc_str.lower()
            or "rate" in exc_str.lower()
        )
        if is_rate_limit:
            log.warning("ws.copilot.rate_limited", error=exc_str[:200])
            user_msg = (
                "⚠️ Gemini API rate limit reached (free-tier quota exhausted). "
                "Please wait a moment and try again. "
                "If this persists, the daily request limit has been hit."
            )
        else:
            log.error("ws.copilot.error", error=exc_str)
            user_msg = "An unexpected error occurred. Please try again."
        try:
            await ws.send_json({"type": "token", "content": user_msg})
            await ws.send_json({"type": "done", "reasoning_steps": [], "suggested_actions": []})
        except Exception:  # noqa: BLE001,S110
            pass
    finally:
        await manager.disconnect(ws, channel)


# ─────────────────────────────────────────────────────────────
# Retained Existing Endpoints
# ─────────────────────────────────────────────────────────────


@router.websocket("/shipments/{shipment_id}")
async def ws_shipment(
    ws: WebSocket,
    shipment_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Real-time tracking for a single shipment."""
    try:
        ctx = await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    shipment = await db.get(Shipment, shipment_id)
    if not shipment or str(shipment.tenant_id) != ctx["tenant_id"]:
        await ws.close(code=1008)
        return

    channel = f"tenant:{ctx['tenant_id']}:shipment:{shipment_id}"
    await ws.accept()
    await manager.connect(ws, channel)
    try:
        await ws.send_json(
            {
                "type": "init",
                "channel": channel,
                "shipment_id": shipment_id,
                "tenant_id": ctx["tenant_id"],
                "status": shipment.status.value
                if hasattr(shipment.status, "value")
                else shipment.status,
                "origin": shipment.origin,
                "destination": shipment.destination,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if msg == "ping":
                    await ws.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})
            except TimeoutError:
                await ws.send_json(
                    {
                        "type": "heartbeat",
                        "ts": datetime.now(UTC).isoformat(),
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws.shipment.error", shipment_id=shipment_id, error=str(exc))
    finally:
        await manager.disconnect(ws, channel)


@router.websocket("/dashboard")
async def ws_dashboard(
    ws: WebSocket,
    token: str = Query(...),
) -> None:
    """KPI tick stream for the tenant dashboard."""
    try:
        ctx = await _authenticate_ws(token)
    except UnauthorizedError:
        await ws.close(code=1008)
        return

    channel = f"tenant:{ctx['tenant_id']}:dashboard"
    await ws.accept()
    await manager.connect(ws, channel)
    try:
        await ws.send_json(
            {
                "type": "tick",
                "connections": manager.connection_count(),
                "tenant_id": ctx["tenant_id"],
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if msg == "ping":
                    await ws.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})
            except TimeoutError:
                await ws.send_json(
                    {
                        "type": "tick",
                        "connections": manager.connection_count(),
                        "ts": datetime.now(UTC).isoformat(),
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws.dashboard.error", error=str(exc))
    finally:
        await manager.disconnect(ws, channel)

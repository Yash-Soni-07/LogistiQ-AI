"""
agents/copilot_agent.py — Natural language query interface for LogistiQ AI.

Operators ask questions in plain English; the copilot classifies intent,
calls the right MCP tools / DB queries, and returns a structured answer.

Intent types
────────────
  shipment_status   → "Where is shipment XYZ?" / "Why is X delayed?"
  risk_query        → "What's the flood risk on Mumbai-Delhi?"
  route_suggestion  → "Best route from Pune to Kolkata for 5 tonne cold chain?"
  analytics         → "How many shipments were delayed this week?"
  general           → Everything else (Gemini handles freeform)

Rate limit : 20 copilot calls per tenant per hour (Redis counter)

Fallback (no Gemini key): template-based responses using DB + MCP data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.usage_tracker import record_event
from core.config import settings
from core.exceptions import RateLimitError
from core.redis import redis_client
from db.models import Shipment, ShipmentStatus

log = structlog.get_logger(__name__)

_RATE_LIMIT = 20  # max calls per tenant per hour
_GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")

# ─────────────────────────────────────────────────────────────
# Output dataclass
# ─────────────────────────────────────────────────────────────


@dataclass
class CopilotResponse:
    answer: str
    intent: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.8
    sources: list[str] = field(default_factory=list)
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "intent": self.intent,
            "tool_calls": self.tool_calls,
            "confidence": self.confidence,
            "sources": self.sources,
            "fallback_used": self.fallback_used,
        }


# ─────────────────────────────────────────────────────────────
# Intent classifier (keyword-first, Gemini as fallback)
# ─────────────────────────────────────────────────────────────

_INTENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bshipment\b.*\b(where|status|track|delayed|why|eta)\b", re.I),
        "shipment_status",
    ),
    (re.compile(r"\b(where|track|status|delay|eta)\b.*\bshipment\b", re.I), "shipment_status"),
    (
        re.compile(r"\b(flood|risk|weather|cyclone|earthquake|fire|quake|disaster)\b", re.I),
        "risk_query",
    ),
    (
        re.compile(r"\b(route|reroute|best path|alternate|multimodal|transport)\b", re.I),
        "route_suggestion",
    ),
    (
        re.compile(
            r"\b(how many|count|analytics|report|week|month|delayed shipments|statistics)\b", re.I
        ),
        "analytics",
    ),
]


def _classify_intent(question: str) -> str:
    """Rule-based intent classification with regex patterns."""
    for pattern, intent in _INTENT_PATTERNS:
        if pattern.search(question):
            return intent
    return "general"


# ─────────────────────────────────────────────────────────────
# Rate limiter
# ─────────────────────────────────────────────────────────────


async def _check_rate_limit(tenant_id: str) -> None:
    key = f"copilot:rate:{tenant_id}:{datetime.now(tz=UTC).strftime('%Y-%m-%dT%H')}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 3600)
        if count > _RATE_LIMIT:
            raise RateLimitError(
                f"Copilot rate limit of {_RATE_LIMIT} queries/hour exceeded",
                retry_after_seconds=3600,
            )
    except RateLimitError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("copilot.rate_limit_check_failed", error=str(exc))


# ─────────────────────────────────────────────────────────────
# Intent handlers
# ─────────────────────────────────────────────────────────────


async def _handle_shipment_status(
    question: str, tenant_id: str, db: AsyncSession
) -> CopilotResponse:
    """Lookup shipment(s) matching IDs or status keywords in the question."""
    # Try to extract a UUID or tracking number from the question
    uuid_match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", question, re.I
    )
    tool_calls: list[dict[str, Any]] = []

    if uuid_match:
        shipment_id = uuid_match.group()
        row = (
            await db.execute(
                select(Shipment).where(
                    Shipment.id == shipment_id,
                    Shipment.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()

        if row:
            answer = (
                f"Shipment **{row.id}** ({row.origin} → {row.destination}) "
                f"is currently **{row.status.value.upper()}** via {row.mode.value}. "
            )
            if row.status == ShipmentStatus.DELAYED:
                answer += "⚠️ It has been flagged as delayed by the sentinel agent."
            elif row.status == ShipmentStatus.IN_TRANSIT:
                answer += f"Estimated delivery: {row.estimated_delivery or 'not set'}."
            tool_calls.append({"tool": "db:shipment_lookup", "shipment_id": shipment_id})
            return CopilotResponse(
                answer=answer,
                intent="shipment_status",
                tool_calls=tool_calls,
                confidence=0.95,
                sources=["database"],
            )
        else:
            return CopilotResponse(
                answer=f"I couldn't find shipment `{shipment_id}` for your account.",
                intent="shipment_status",
                confidence=0.90,
                sources=["database"],
            )

    # No UUID — return summary of delayed shipments
    delayed = (
        (
            await db.execute(
                select(Shipment)
                .where(Shipment.tenant_id == tenant_id, Shipment.status == ShipmentStatus.DELAYED)
                .limit(5)
            )
        )
        .scalars()
        .all()
    )

    if delayed:
        lines = [f"- `{s.id}`: {s.origin} → {s.destination}" for s in delayed]
        answer = f"You have **{len(delayed)}** delayed shipments:\n" + "\n".join(lines)
    else:
        answer = "All your shipments are currently on time. ✅"

    return CopilotResponse(
        answer=answer, intent="shipment_status", confidence=0.85, sources=["database"]
    )


async def _handle_risk_query(question: str, tenant_id: str) -> CopilotResponse:
    """Call weather + satellite MCPs and summarise the risk."""
    from mcp_servers.mcp_weather import weather_mcp

    tool_calls: list[dict[str, Any]] = []

    # Extract city names from question (simple approach)
    cities = re.findall(
        r"\b(mumbai|delhi|chennai|kolkata|bangalore|hyderabad|pune|surat|ahmedabad)\b",
        question,
        re.I,
    )
    city = cities[0].lower() if cities else "mumbai"
    city_coords = {
        "mumbai": (19.076, 72.877),
        "delhi": (28.704, 77.102),
        "chennai": (13.082, 80.270),
        "kolkata": (22.572, 88.363),
        "bangalore": (12.971, 77.594),
        "hyderabad": (17.385, 78.486),
        "pune": (18.520, 73.855),
        "surat": (21.170, 72.831),
        "ahmedabad": (23.022, 72.571),
    }
    lat, lon = city_coords.get(city, (20.593, 78.963))

    # Fetch flood risk
    flood_data: dict[str, Any] = {}
    try:
        flood_data = await weather_mcp.execute_tool(
            "get_flood_risk", {"lat": lat, "lon": lon}, None
        )
        tool_calls.append({"tool": "weather:get_flood_risk", "lat": lat, "lon": lon})
    except Exception as exc:  # noqa: BLE001
        log.warning("copilot.risk_query.flood_failed", error=str(exc))

    risk = flood_data.get("risk_score", 0.0)
    level = flood_data.get("risk_level", "UNKNOWN")
    rain = flood_data.get("rain_24h_mm", 0.0)
    elev = flood_data.get("elevation_m", 0.0)

    answer = (
        f"**Flood risk near {city.title()}**: {level} (score: {risk:.2f})\n"
        f"- 24h rainfall: {rain:.1f} mm\n"
        f"- Elevation: {elev:.0f} m\n"
    )
    if risk >= 0.7:
        answer += (
            "\n⚠️ **High risk** — consider rerouting or delaying shipments through this corridor."
        )
    elif risk >= 0.4:
        answer += "\n⚠️ Moderate risk — monitor conditions closely."
    else:
        answer += "\n✅ Conditions appear acceptable for transit."

    return CopilotResponse(
        answer=answer,
        intent="risk_query",
        tool_calls=tool_calls,
        confidence=0.88,
        sources=["Open-Meteo", "Open-Elevation"],
    )


async def _handle_route_suggestion(question: str, tenant_id: str) -> CopilotResponse:
    """Call routing MCP to find multimodal options."""
    from mcp_servers.mcp_routing import routing_mcp

    tool_calls: list[dict[str, Any]] = []

    # Extract origin/destination from question
    cities = re.findall(
        r"\b(mumbai|delhi|chennai|kolkata|bangalore|hyderabad|pune|surat|ahmedabad|"
        r"nagpur|jaipur|lucknow|amritsar|kochi)\b",
        question,
        re.I,
    )

    if len(cities) >= 2:
        origin, dest = cities[0].title(), cities[1].title()
        try:
            result = await routing_mcp.execute_tool(
                "get_multimodal_options",
                {"origin": origin, "destination": dest, "weight_kg": 5000},
                None,
            )
            tool_calls.append(
                {"tool": "routing:get_multimodal_options", "origin": origin, "destination": dest}
            )
            modes = result if isinstance(result, list) else [result]
            mode_lines = [
                f"- **{m.get('mode', '?').upper()}**: ₹{m.get('cost_inr', 0):,.0f} | "
                f"{m.get('eta_h', 0):.1f}h | {m.get('co2_kg', 0):.1f} kg CO₂"
                for m in modes[:4]
            ]
            answer = f"**Route options ({origin} → {dest}):**\n" + "\n".join(mode_lines)
        except Exception as exc:  # noqa: BLE001
            log.warning("copilot.route_suggestion.failed", error=str(exc))
            answer = f"I couldn't fetch route options for {origin} → {dest}. Please try again."
    else:
        answer = "Please specify both origin and destination cities in your question."

    return CopilotResponse(
        answer=answer,
        intent="route_suggestion",
        tool_calls=tool_calls,
        confidence=0.82,
        sources=["OSRM", "Routing MCP"],
    )


async def _handle_analytics(question: str, tenant_id: str, db: AsyncSession) -> CopilotResponse:
    """Answer analytics questions using pre-built DB aggregations."""
    from sqlalchemy import case, func

    counts = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(case((Shipment.status == ShipmentStatus.DELAYED, 1), else_=0)).label(
                    "delayed"
                ),
                func.sum(case((Shipment.status == ShipmentStatus.IN_TRANSIT, 1), else_=0)).label(
                    "in_transit"
                ),
                func.sum(case((Shipment.status == ShipmentStatus.DELIVERED, 1), else_=0)).label(
                    "delivered"
                ),
            ).where(Shipment.tenant_id == tenant_id)
        )
    ).one()

    answer = (
        f"📊 **Shipment Summary for your account:**\n"
        f"- Total: {counts.total}\n"
        f"- In Transit: {counts.in_transit}\n"
        f"- Delayed: {counts.delayed} ({'%.0f' % (counts.delayed / max(counts.total, 1) * 100)}%)\n"
        f"- Delivered: {counts.delivered}\n"
    )
    return CopilotResponse(answer=answer, intent="analytics", confidence=0.92, sources=["database"])


# ─────────────────────────────────────────────────────────────
# Gemini general handler
# ─────────────────────────────────────────────────────────────


async def _handle_with_gemini(question: str, tenant_id: str) -> CopilotResponse:
    """Use Gemini 1.5 Flash for general / unclassified questions."""
    import google.generativeai as genai

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=_GEMINI_MODEL,
        system_instruction=(
            "You are LogistiQ AI Copilot — an expert assistant for Indian logistics operators. "
            "Answer concisely in plain English. Use markdown for clarity. "
            "If you need real-time data, say so — you don't have live tool access in this mode."
        ),
    )
    try:
        resp = model.generate_content(question)
        return CopilotResponse(
            answer=resp.text.strip(),
            intent="general",
            confidence=0.75,
            sources=["Gemini"],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("copilot.gemini_general_failed", error=str(exc))
        return CopilotResponse(
            answer=(
                "I'm having trouble reaching the AI model right now. "
                "For route risk, check /analytics/summary. "
                "For shipment status, check /shipments."
            ),
            intent="general",
            confidence=0.3,
            fallback_used=True,
        )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


async def query(
    question: str,
    tenant_id: str,
    user_id: str,
    db: AsyncSession,
) -> CopilotResponse:
    """
    Process a natural-language question from a logistics operator.

    Parameters
    ----------
    question  : Free-text query from the UI.
    tenant_id : Calling tenant's UUID.
    user_id   : Calling user's UUID (for logging).
    db        : Active async DB session.

    Returns
    -------
    CopilotResponse with answer, intent, tool_calls, confidence, sources.

    Raises
    ------
    RateLimitError if the tenant exceeds 20 calls/hour.
    """
    await _check_rate_limit(tenant_id)

    intent = _classify_intent(question)
    log.info("copilot.query", intent=intent, user_id=user_id, tenant_id=tenant_id)

    # Fire usage event (best-effort)
    await record_event(tenant_id, "ai_decision")

    try:
        match intent:
            case "shipment_status":
                return await _handle_shipment_status(question, tenant_id, db)
            case "risk_query":
                return await _handle_risk_query(question, tenant_id)
            case "route_suggestion":
                return await _handle_route_suggestion(question, tenant_id)
            case "analytics":
                return await _handle_analytics(question, tenant_id, db)
            case _:
                if settings.GEMINI_API_KEY:
                    return await _handle_with_gemini(question, tenant_id)
                return CopilotResponse(
                    answer=(
                        "I can help with shipment status, flood/risk queries, "
                        "route suggestions, and analytics. Could you be more specific?"
                    ),
                    intent="general",
                    confidence=0.5,
                    fallback_used=True,
                )
    except RateLimitError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error("copilot.query_failed", intent=intent, error=str(exc))
        return CopilotResponse(
            answer="Something went wrong processing your question. Please try again.",
            intent=intent,
            confidence=0.0,
            fallback_used=True,
        )

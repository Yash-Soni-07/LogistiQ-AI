import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

import pybreaker
import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from core.config import settings
from core.redis import redis_client

log = structlog.get_logger(__name__)

# ── Circuit Breakers ──
gemini_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=120)


# ── 1. Schema Normalization ──
class DisruptionEvent(BaseModel):
    event_id: str
    affected_segments: list[str]
    event_type: str
    severity: str
    description: str
    timestamp: str
    lat: float
    lon: float


# ── 2. LangGraph State Definition ──
class AgentState(TypedDict):
    disruption_event: dict[str, Any]
    tenant_id: str
    affected_shipments: list[dict[str, Any]]
    candidate_routes: dict[str, Any]
    sla_at_risk: list[dict[str, Any]]
    selected_actions: list[dict[str, Any]]
    reasoning_steps: list[str]
    tool_call_history: list[dict[str, Any]]
    fallback_used: bool
    human_escalated: bool
    trace_id: str
    gemini_tokens_used: int
    total_cost_delta_inr: float


# ── 3. Tool Definitions (Langchain @tool) ──
@tool
def get_affected_shipments(
    segment_id: str, tenant_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """Get SLA-critical shipments affected by a disrupted segment."""
    return [{"shipment_id": "ship-1", "critical": True}]


@tool
def get_alternate_routes(shipment_ids: list[str], blocked_segment_id: str) -> dict[str, Any]:
    """Get top 3 alternate routes per shipment."""
    # TODO(Phase 3): Wire to routing MCP
    return {"ship-1": [{"route_id": "alt-route-1", "cost_delta": 10000, "delay_hours": 2}]}


@tool
def get_sla_breach_risk(shipment_ids: list[str]) -> list[dict[str, Any]]:
    """Get SLA breach probability and hours to deadline."""
    return [{"shipment_id": "ship-1", "breach_prob": 0.8, "hours_left": 12}]


@tool
def book_carrier(shipment_id: str, route_id: str, carrier_id: str) -> dict[str, Any]:
    """Book a carrier for an alternate route."""
    # TODO(Phase 3): Wire to routing MCP
    return {"status": "booked", "booking_id": "bk-123"}


@tool
def send_alert(
    recipient_type: str, ids: list[str], message: str, alert_type: str
) -> dict[str, Any]:
    """Send an alert to specific recipients."""
    return {"status": "sent", "delivered_count": len(ids)}


@tool
def log_decision(
    reasoning_summary: str, actions_taken: list[dict], cost_impact: float, co2_impact: float
) -> dict[str, Any]:
    """Log the final decision and reasoning."""
    return {"decision_id": "dec-123", "status": "logged"}


tools = [
    get_affected_shipments,
    get_alternate_routes,
    get_sla_breach_risk,
    book_carrier,
    send_alert,
    log_decision,
]
tool_map = {t.name: t for t in tools}


# ── 4. Graph Nodes ──
async def receive_disruption_node(state: AgentState) -> AgentState:
    raw_event = state["disruption_event"]
    trace_id = str(uuid.uuid4())

    # Normalize schema
    if "segment_id" in raw_event:
        affected = [raw_event["segment_id"]]
        event_type = raw_event.get("event_type", "unknown")
        severity = raw_event.get("severity", "high")
        desc = f"{event_type.capitalize()} on {raw_event.get('highway_code', 'segment')}"
    else:
        affected = raw_event.get("affected_segment_ids", [])
        event_type = "news_based"
        severity = "high"
        if raw_event.get("source_count", 1) >= 5:
            severity = "critical"
        desc = raw_event.get("description", "")

    normalized = DisruptionEvent(
        event_id=raw_event.get("event_id", str(uuid.uuid4())),
        affected_segments=affected,
        event_type=event_type,
        severity=severity,
        description=desc,
        timestamp=raw_event.get("timestamp", datetime.now(UTC).isoformat()),
        lat=float(raw_event.get("lat", 0.0)),
        lon=float(raw_event.get("lon", 0.0)),
    )

    return {
        **state,
        "disruption_event": normalized.model_dump(),
        "trace_id": trace_id,
        "fallback_used": False,
        "human_escalated": False,
        "gemini_tokens_used": 0,
        "total_cost_delta_inr": 0.0,
        "tenant_id": state.get("tenant_id", "default_tenant"),
    }


async def fetch_context_node(state: AgentState) -> AgentState:
    log.info(
        "agent.node",
        node_name="fetch_context_node",
        trace_id=state["trace_id"],
        state_keys=list(state.keys()),
    )
    segments = state["disruption_event"]["affected_segments"]

    # Call async tools directly for now as stubs
    # In real execution, we'd use gather over actual DB functions
    shipments = []
    for seg in segments:
        res = get_affected_shipments.invoke({"segment_id": seg, "tenant_ids": [state["tenant_id"]]})
        shipments.extend(res)

    shipment_ids = [s["shipment_id"] for s in shipments]
    sla_risks = get_sla_breach_risk.invoke({"shipment_ids": shipment_ids}) if shipment_ids else []

    return {**state, "affected_shipments": shipments, "sla_at_risk": sla_risks}


async def evaluate_routes_node(state: AgentState) -> AgentState:
    log.info(
        "agent.node",
        node_name="evaluate_routes_node",
        trace_id=state["trace_id"],
        state_keys=list(state.keys()),
    )
    shipment_ids = [s["shipment_id"] for s in state["affected_shipments"]]
    segments = state["disruption_event"]["affected_segments"]

    candidate_routes = {}
    if shipment_ids and segments:
        res = get_alternate_routes.invoke(
            {"shipment_ids": shipment_ids, "blocked_segment_id": segments[0]}
        )
        candidate_routes = res

    return {**state, "candidate_routes": candidate_routes}


async def gemini_select_node(state: AgentState) -> AgentState:
    log.info(
        "agent.node",
        node_name="gemini_select_node",
        trace_id=state["trace_id"],
        state_keys=list(state.keys()),
    )

    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        api_key=(
            settings.GEMINI_API_KEY.get_secret_value()
            if hasattr(settings.GEMINI_API_KEY, "get_secret_value")
            else settings.GEMINI_API_KEY
        ),
        temperature=0.0,
    ).bind_tools(tools)

    system_prompt = SystemMessage(
        content=(
            "You are an expert logistics AI. You must prioritize SLA > Cost > Carbon. "
            "Analyze the state and use tools to make re-routing decisions or alerts. "
            "Your final response MUST include tool calls for book_carrier or send_alert, "
            "along with log_decision. Do not execute them yourself, just return the tool calls."
        )
    )

    context = HumanMessage(content=f"Current State: {json.dumps(state, default=str)}")
    messages = [system_prompt, context]

    tokens = state.get("gemini_tokens_used", 0)

    # Simple ReAct loop (internal)
    async def _run_loop():
        nonlocal tokens
        for _ in range(8):
            response = await llm.ainvoke(messages)

            # Count tokens (approx or via usage_metadata if available)
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens += response.usage_metadata.get("total_tokens", 0)

            messages.append(response)

            if not response.tool_calls:
                break

            for tc in response.tool_calls:
                tool_func = tool_map.get(tc["name"])
                if tool_func:
                    # Execute tool to feed result back to LLM
                    tool_res = await tool_func.ainvoke(tc["args"])
                    messages.append(
                        ToolMessage(content=json.dumps(tool_res), tool_call_id=tc["id"])
                    )
                else:
                    messages.append(ToolMessage(content="Tool not found", tool_call_id=tc["id"]))

        return response

    try:

        @gemini_breaker
        async def call_llm():
            return await asyncio.wait_for(_run_loop(), timeout=30.0)

        final_response = await call_llm()

        # Extract actions (tool calls) from the final response
        actions = []
        if isinstance(final_response, AIMessage) and final_response.tool_calls:
            actions = final_response.tool_calls

        return {**state, "selected_actions": actions, "gemini_tokens_used": tokens}
    except Exception as exc:
        log.error("agent.gemini.error", error=str(exc))
        raise


async def execute_actions_node(state: AgentState) -> AgentState:
    log.info(
        "agent.node",
        node_name="execute_actions_node",
        trace_id=state["trace_id"],
        state_keys=list(state.keys()),
    )
    cost_delta = 0.0
    # In reality, parse actual cost from the LLM outputs or candidate routes
    # For now, hardcode mock extraction
    for action in state["selected_actions"]:
        if action["name"] == "book_carrier":
            cost_delta += 10000.0  # mock

    return {**state, "total_cost_delta_inr": cost_delta}


async def vrp_fallback_node(state: AgentState) -> AgentState:
    log.info(
        "agent.node",
        node_name="vrp_fallback_node",
        trace_id=state["trace_id"],
        state_keys=list(state.keys()),
    )
    return {**state, "fallback_used": True}


async def human_escalate_node(state: AgentState) -> AgentState:
    log.info(
        "agent.node",
        node_name="human_escalate_node",
        trace_id=state["trace_id"],
        state_keys=list(state.keys()),
    )
    return {**state, "human_escalated": True}


async def log_and_notify_node(state: AgentState) -> AgentState:
    log.info(
        "agent.node",
        node_name="log_and_notify_node",
        trace_id=state["trace_id"],
        state_keys=list(state.keys()),
    )
    tenant_id = state.get("tenant_id", "default_tenant")

    disruption = state["disruption_event"]
    actions_list = [tc["name"] for tc in state.get("selected_actions", [])]

    payload = {
        "trace_id": state["trace_id"],
        "timestamp": datetime.now(UTC).isoformat(),
        "disruption": disruption,
        "actions": actions_list,
        "fallback_used": state.get("fallback_used", False),
        "human_escalated": state.get("human_escalated", False),
        # Readable fields for frontend dashboard
        "description": disruption.get("description", "Agent decision processed"),
        "severity": disruption.get("severity", "medium"),
        "message": f"Decision agent processed {disruption.get('event_type', 'event')}: {', '.join(actions_list) if actions_list else 'monitoring'}",  # noqa: E501
        "shipment_id": disruption.get("shipment_id"),
    }

    # Write to DB, publish WS update, send alerts
    await redis_client.publish(f"agent_log:{tenant_id}", json.dumps(payload))
    await redis_client.lpush(f"agent_log:{tenant_id}", json.dumps(payload))
    await redis_client.ltrim(f"agent_log:{tenant_id}", 0, 99)

    # Also publish VRP results for Route Optimizer page
    vrp_payload = {
        "trace_id": state["trace_id"],
        "timestamp": datetime.now(UTC).isoformat(),
        "disruption": disruption,
        "alternate_routes": state.get("candidate_routes", {}),
        "selected_actions": actions_list,
        "fallback_used": state.get("fallback_used", False),
        "human_escalated": state.get("human_escalated", False),
        "gemini_tokens_used": state.get("gemini_tokens_used", 0),
        "total_cost_delta_inr": state.get("total_cost_delta_inr", 0.0),
    }
    await redis_client.publish(f"vrp_results:{tenant_id}", json.dumps(vrp_payload))
    await redis_client.setex(f"vrp_results:{tenant_id}:latest", 3600, json.dumps(vrp_payload))

    return state


# ── 5. Conditional Edges ──
def route_after_evaluate(state: AgentState) -> str:
    # If breaker is open, pybreaker state is 'open'
    if gemini_breaker.current_state == "open":
        return "vrp_fallback"
    return "gemini_select"


def route_after_gemini(state: AgentState) -> str:
    if state.get("total_cost_delta_inr", 0) > 150000:
        return "human_escalate"
    return "execute_actions"


# ── 6. Build Graph ──
builder = StateGraph(AgentState)
builder.add_node("receive_disruption", receive_disruption_node)
builder.add_node("fetch_context", fetch_context_node)
builder.add_node("evaluate_routes", evaluate_routes_node)
builder.add_node("gemini_select", gemini_select_node)
builder.add_node("execute_actions", execute_actions_node)
builder.add_node("vrp_fallback", vrp_fallback_node)
builder.add_node("human_escalate", human_escalate_node)
builder.add_node("log_and_notify", log_and_notify_node)

builder.add_edge(START, "receive_disruption")
builder.add_edge("receive_disruption", "fetch_context")
builder.add_edge("fetch_context", "evaluate_routes")

builder.add_conditional_edges(
    "evaluate_routes",
    route_after_evaluate,
    {"vrp_fallback": "vrp_fallback", "gemini_select": "gemini_select"},
)

builder.add_conditional_edges(
    "gemini_select",
    route_after_gemini,
    {"human_escalate": "human_escalate", "execute_actions": "execute_actions"},
)

builder.add_edge("vrp_fallback", "log_and_notify")
builder.add_edge("execute_actions", "log_and_notify")
builder.add_edge("human_escalate", "log_and_notify")
builder.add_edge("log_and_notify", END)

decision_graph = builder.compile()


class DecisionAgent:
    def __init__(self):
        self.graph = decision_graph
        self._subscriber_task = None

    async def handle_disruption(self, raw_event: dict[str, Any]) -> None:
        initial_state = AgentState(
            disruption_event=raw_event,
            tenant_id="t-123",  # typically extracted or default
            affected_shipments=[],
            candidate_routes={},
            sla_at_risk=[],
            selected_actions=[],
            reasoning_steps=[],
            tool_call_history=[],
            fallback_used=False,
            human_escalated=False,
            trace_id="",
            gemini_tokens_used=0,
            total_cost_delta_inr=0.0,
        )
        try:
            await self.graph.ainvoke(initial_state)
        except Exception as exc:
            log.error("agent.graph.error", error=str(exc))

    async def subscribe_disruptions(self) -> None:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("disruptions")

        semaphore = asyncio.Semaphore(5)

        async def _process(msg: str):
            async with semaphore:
                try:
                    event = json.loads(msg)
                    await self.handle_disruption(event)
                except Exception as e:
                    log.error("agent.subscriber.parse_error", error=str(e))

        log.info("decision_agent.subscriber.started")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    asyncio.create_task(_process(data))
        except asyncio.CancelledError:
            log.info("decision_agent.subscriber.stopped")
            await pubsub.unsubscribe("disruptions")

    async def start(self) -> None:
        if self._subscriber_task is None:
            self._subscriber_task = asyncio.create_task(self.subscribe_disruptions())

    async def stop(self) -> None:
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
            self._subscriber_task = None

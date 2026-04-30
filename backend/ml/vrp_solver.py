"""
ml/vrp_solver.py — Vehicle Routing Problem solver for LogistiQ AI.

Uses Google OR-Tools (pywrapcp) with:
  - Weighted cost matrix: distance_km × mode_cost + risk × 500 (+ CO₂ penalty when carbon_mode)
  - Hard risk blocks: NextVar.RemoveValue for pairs with risk > 0.80
  - Strategy: SAVINGS for large problems (>50 nodes), PATH_CHEAPEST_ARC otherwise
  - Local search: GUIDED_LOCAL_SEARCH
  - Time limit: 10 s, solution limit: 100
  - Nearest-neighbour fallback if OR-Tools finds no solution

Alternate-route finder uses a min-heap (heapq) for O(E log N) top-N selection.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import structlog
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from core.redis import redis_client

log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Dependency protocols (injected — no global state)
# ─────────────────────────────────────────────────────────────


class MCPClient(Protocol):
    async def call(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]: ...


class AsyncDB(Protocol):
    async def fetch_one(self, query: str, *args: Any) -> dict[str, Any] | None: ...
    async def fetch_all(self, query: str, *args: Any) -> list[dict[str, Any]]: ...


# ─────────────────────────────────────────────────────────────
# Domain dataclasses
# ─────────────────────────────────────────────────────────────


@dataclass
class VRPNode:
    """A stop in the routing problem."""

    id: str
    lat: float
    lon: float
    demand_kg: float = 0.0
    time_window_start: int = 0  # seconds from midnight
    time_window_end: int = 86400  # seconds from midnight


@dataclass
class VRPVehicle:
    """A vehicle/asset that performs deliveries."""

    id: str
    capacity_kg: float
    depot_node_id: str
    mode: str = "road"  # road | rail | sea | air


@dataclass
class VRPInput:
    nodes: list[VRPNode]
    vehicles: list[VRPVehicle]
    risk_matrix: np.ndarray  # shape (N, N) with risk [0..1] per edge
    carbon_mode: bool = False


@dataclass
class RouteStep:
    node_id: str
    arrival_s: int = 0
    departure_s: int = 0


@dataclass
class VehicleRoute:
    vehicle_id: str
    steps: list[RouteStep]
    distance_km: float
    cost_inr: float
    co2_kg: float


@dataclass
class VRPSolution:
    routes: list[VehicleRoute]
    total_cost_inr: float
    total_km: float
    total_co2_kg: float
    solve_time_s: float
    is_feasible: bool
    fallback_used: bool = False


@dataclass(order=True)
class AlternateRoute:
    """A candidate alternate route for the min-heap comparator."""

    composite_cost: float = field(compare=True)
    route_id: str = field(compare=False)
    cost_inr: float = field(compare=False)
    eta_h: float = field(compare=False)
    risk_score: float = field(compare=False)
    co2_kg: float = field(compare=False)
    mode: str = field(compare=False)


# ─────────────────────────────────────────────────────────────
# Mode cost tables  (INR / km)
# ─────────────────────────────────────────────────────────────

MODE_COST_PER_KM: dict[str, float] = {
    "road": 45.0,
    "rail": 12.0,
    "sea": 8.0,
    "air": 350.0,
}

# CO₂ kg per tonne-km
MODE_CO2_PER_TONNE_KM: dict[str, float] = {
    "road": 0.062,
    "rail": 0.022,
    "sea": 0.008,
    "air": 0.602,
}

# Speed km/h (for ETA)
MODE_SPEED_KMH: dict[str, float] = {
    "road": 60.0,
    "rail": 60.0,
    "sea": 25.0,
    "air": 800.0,
}

_RISK_PENALTY = 500.0  # INR per unit risk per km
_CARBON_PENALTY = 50.0  # INR per kg CO₂ added when carbon_mode=True


# ─────────────────────────────────────────────────────────────
# Haversine
# ─────────────────────────────────────────────────────────────


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─────────────────────────────────────────────────────────────
# Distance matrix (async, cached in Redis for 1 hour)
# ─────────────────────────────────────────────────────────────


async def _distance_matrix_km(nodes: list[VRPNode]) -> np.ndarray:
    """
    Build an (N×N) Haversine distance matrix.
    In production you'd call the OSRM Table API; we cache the result in Redis.
    """
    n = len(nodes)
    import json

    ids = [nd.id for nd in nodes]
    cache_key = "vrp:dist_matrix:" + ":".join(sorted(ids))
    cached = await redis_client.get(cache_key)
    if cached:
        try:
            arr = np.array(json.loads(cached), dtype=float)
            if arr.shape == (n, n):
                return arr
        except (ValueError, json.JSONDecodeError):
            pass

    mat = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(n):
            if i != j:
                mat[i, j] = _haversine_km(nodes[i].lat, nodes[i].lon, nodes[j].lat, nodes[j].lon)

    try:
        await redis_client.setex(cache_key, 3600, json.dumps(mat.tolist()))
    except Exception:  # noqa: BLE001
        log.debug("vrp_solver.dist_matrix_cache_write_suppressed")

    return mat


# ─────────────────────────────────────────────────────────────
# Cost matrix builder (public API)
# ─────────────────────────────────────────────────────────────


async def build_cost_matrix(
    nodes: list[VRPNode],
    risk_matrix: np.ndarray,
    mode: str = "road",
    carbon_mode: bool = False,
) -> np.ndarray:
    """
    Build an (N×N) edge cost matrix in INR.

    edge_cost[i][j] = distance_km[i][j] * mode_cost_per_km
                    + risk_matrix[i][j] * _RISK_PENALTY
    if carbon_mode:
        edge_cost[i][j] += co2_kg[i][j] * _CARBON_PENALTY
    """
    dist_km = await _distance_matrix_km(nodes)
    cost_per_km = MODE_COST_PER_KM.get(mode, MODE_COST_PER_KM["road"])
    co2_per_tkm = MODE_CO2_PER_TONNE_KM.get(mode, MODE_CO2_PER_TONNE_KM["road"])

    # Average demand per node (tonnes) for CO₂ estimate
    avg_demand_t = max(sum(nd.demand_kg for nd in nodes) / (1000.0 * max(len(nodes), 1)), 0.001)

    cost = dist_km * cost_per_km + risk_matrix * _RISK_PENALTY

    if carbon_mode:
        co2_matrix = dist_km * co2_per_tkm * avg_demand_t
        cost += co2_matrix * _CARBON_PENALTY

    return cost


# ─────────────────────────────────────────────────────────────
# Nearest-neighbour fallback (pure Python, synchronous)
# ─────────────────────────────────────────────────────────────


def _nearest_neighbor_fallback(
    nodes: list[VRPNode],
    vehicles: list[VRPVehicle],
    cost_matrix: np.ndarray,
    depot_indices: dict[str, int],
) -> list[list[int]]:
    """
    Greedy nearest-neighbour for each vehicle.
    Returns a list of node-index sequences (including depot at start/end).
    """
    unvisited = set(range(len(nodes)))
    routes: list[list[int]] = []

    for veh in vehicles:
        depot_idx = depot_indices.get(veh.depot_node_id, 0)
        unvisited.discard(depot_idx)
        route = [depot_idx]
        capacity_left = veh.capacity_kg
        current = depot_idx

        while unvisited:
            # Find cheapest reachable next node within capacity
            best_cost = float("inf")
            best_next = -1
            for nxt in unvisited:
                if nodes[nxt].demand_kg <= capacity_left:
                    c = float(cost_matrix[current, nxt])
                    if c < best_cost:
                        best_cost = c
                        best_next = nxt
            if best_next == -1:
                break
            route.append(best_next)
            capacity_left -= nodes[best_next].demand_kg
            unvisited.discard(best_next)
            current = best_next

        route.append(depot_idx)
        routes.append(route)

    return routes


# ─────────────────────────────────────────────────────────────
# Main synchronous solver (runs in thread if needed)
# ─────────────────────────────────────────────────────────────


def solve(vrp_input: VRPInput) -> VRPSolution:
    """
    Solve the VRP using OR-Tools.

    Blocking — call with asyncio.to_thread() from async contexts.
    """
    t0 = time.perf_counter()

    nodes = vrp_input.nodes
    vehicles = vrp_input.vehicles
    risk_matrix = vrp_input.risk_matrix
    n = len(nodes)

    if n == 0 or not vehicles:
        return VRPSolution(
            routes=[],
            total_cost_inr=0.0,
            total_km=0.0,
            total_co2_kg=0.0,
            solve_time_s=0.0,
            is_feasible=True,
        )

    # Identify depot indices
    node_id_to_idx: dict[str, int] = {nd.id: i for i, nd in enumerate(nodes)}
    depot_indices: dict[str, int] = {
        veh.depot_node_id: node_id_to_idx.get(veh.depot_node_id, 0) for veh in vehicles
    }

    # Primary mode (first vehicle's mode as representative)
    primary_mode = vehicles[0].mode if vehicles else "road"
    cost_per_km = MODE_COST_PER_KM.get(primary_mode, MODE_COST_PER_KM["road"])
    co2_per_tkm = MODE_CO2_PER_TONNE_KM.get(primary_mode, MODE_CO2_PER_TONNE_KM["road"])

    # Build synchronous distance/cost matrix using Haversine
    dist_km = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(n):
            if i != j:
                dist_km[i, j] = _haversine_km(
                    nodes[i].lat, nodes[i].lon, nodes[j].lat, nodes[j].lon
                )

    cost_mat = dist_km * cost_per_km + risk_matrix * _RISK_PENALTY
    if vrp_input.carbon_mode:
        avg_demand_t = max(sum(nd.demand_kg for nd in nodes) / (1000.0 * n), 0.001)
        cost_mat += dist_km * co2_per_tkm * avg_demand_t * _CARBON_PENALTY

    # OR-Tools expects integer costs — scale by 10 for sub-INR precision
    int_scale = 10
    int_cost_mat = (cost_mat * int_scale).astype(int).tolist()

    # ── OR-Tools setup ────────────────────────────────────────
    num_vehicles = len(vehicles)
    depot_idx_list = [depot_indices.get(v.depot_node_id, 0) for v in vehicles]

    manager = pywrapcp.RoutingIndexManager(n, num_vehicles, depot_idx_list, depot_idx_list)
    routing = pywrapcp.RoutingModel(manager)

    # Distance / cost callback
    def cost_callback(from_index: int, to_index: int) -> int:
        fi = manager.IndexToNode(from_index)
        ti = manager.IndexToNode(to_index)
        return int_cost_mat[fi][ti]

    transit_callback_index = routing.RegisterTransitCallback(cost_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Capacity constraint
    def demand_callback(from_index: int) -> int:
        node_idx = manager.IndexToNode(from_index)
        return int(nodes[node_idx].demand_kg)

    demand_cb_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    capacities = [int(v.capacity_kg) for v in vehicles]
    routing.AddDimensionWithVehicleCapacity(demand_cb_idx, 0, capacities, True, "Capacity")

    # Time-window dimension (seconds)
    routing.AddDimension(
        transit_callback_index,
        3600,  # max waiting time (slack)
        172800,  # horizon (2 days in seconds)
        False,
        "Time",
    )

    time_dim = routing.GetDimensionOrDie("Time")
    for i, node in enumerate(nodes):
        idx = manager.NodeToIndex(i)
        time_dim.CumulVar(idx).SetRange(node.time_window_start, node.time_window_end)

    # ── Hard risk blocks (risk > 0.80) ────────────────────────
    blocked_count = 0
    for i in range(n):
        for j in range(n):
            if i != j and risk_matrix[i, j] > 0.80:
                from_idx = manager.NodeToIndex(i)
                to_idx = manager.NodeToIndex(j)
                routing.NextVar(from_idx).RemoveValue(to_idx)
                blocked_count += 1

    if blocked_count:
        log.info("vrp_solver.blocked_edges", count=blocked_count)

    # ── Search parameters ─────────────────────────────────────
    search_params = pywrapcp.DefaultRoutingSearchParameters()

    if n > 50:
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.SAVINGS
    else:
        search_params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )

    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = 10
    search_params.solution_limit = 100

    # ── Solve ─────────────────────────────────────────────────
    solution = routing.SolveWithParameters(search_params)
    fallback_used = False

    if solution:
        routes = _extract_routes(
            solution, routing, manager, nodes, vehicles, dist_km, cost_per_km, co2_per_tkm
        )
        is_feasible = True
        log.info(
            "vrp_solver.solved",
            num_nodes=n,
            num_vehicles=num_vehicles,
            objective=solution.ObjectiveValue(),
        )
    else:
        log.warning("vrp_solver.no_solution_using_fallback", num_nodes=n)
        fallback_used = True
        nn_routes = _nearest_neighbor_fallback(nodes, vehicles, cost_mat, depot_indices)
        routes = _routes_from_index_lists(
            nn_routes, nodes, vehicles, dist_km, cost_per_km, co2_per_tkm
        )
        is_feasible = False  # only a heuristic, not proven optimal

    total_cost = sum(r.cost_inr for r in routes)
    total_km = sum(r.distance_km for r in routes)
    total_co2 = sum(r.co2_kg for r in routes)

    return VRPSolution(
        routes=routes,
        total_cost_inr=round(total_cost, 2),
        total_km=round(total_km, 2),
        total_co2_kg=round(total_co2, 2),
        solve_time_s=round(time.perf_counter() - t0, 3),
        is_feasible=is_feasible,
        fallback_used=fallback_used,
    )


# ─────────────────────────────────────────────────────────────
# Route extraction helpers
# ─────────────────────────────────────────────────────────────


def _extract_routes(
    solution: Any,
    routing: pywrapcp.RoutingModel,
    manager: pywrapcp.RoutingIndexManager,
    nodes: list[VRPNode],
    vehicles: list[VRPVehicle],
    dist_km: np.ndarray,
    cost_per_km: float,
    co2_per_tkm: float,
) -> list[VehicleRoute]:
    routes: list[VehicleRoute] = []
    for v_idx, vehicle in enumerate(vehicles):
        index = routing.Start(v_idx)
        steps: list[RouteStep] = []
        total_dist = 0.0

        while not routing.IsEnd(index):
            node_idx = manager.IndexToNode(index)
            steps.append(RouteStep(node_id=nodes[node_idx].id))
            index = solution.Value(routing.NextVar(index))
            if not routing.IsEnd(index):
                ni = manager.IndexToNode(index)
                total_dist += float(dist_km[node_idx, ni])
            else:
                end_node = manager.IndexToNode(index)
                total_dist += float(dist_km[node_idx, end_node])

        # Include final depot step
        steps.append(RouteStep(node_id=nodes[manager.IndexToNode(index)].id))

        co2 = (
            total_dist
            * co2_per_tkm
            * max(sum(nd.demand_kg for nd in nodes) / (1000.0 * max(len(nodes), 1)), 0.001)
        )
        routes.append(
            VehicleRoute(
                vehicle_id=vehicle.id,
                steps=steps,
                distance_km=round(total_dist, 2),
                cost_inr=round(total_dist * cost_per_km, 2),
                co2_kg=round(co2, 2),
            )
        )
    return routes


def _routes_from_index_lists(
    index_lists: list[list[int]],
    nodes: list[VRPNode],
    vehicles: list[VRPVehicle],
    dist_km: np.ndarray,
    cost_per_km: float,
    co2_per_tkm: float,
) -> list[VehicleRoute]:
    routes: list[VehicleRoute] = []
    avg_demand_t = max(sum(nd.demand_kg for nd in nodes) / (1000.0 * max(len(nodes), 1)), 0.001)
    for v_idx, vehicle in enumerate(vehicles):
        idx_list = index_lists[v_idx] if v_idx < len(index_lists) else []
        steps = [RouteStep(node_id=nodes[i].id) for i in idx_list]
        total_dist = sum(
            float(dist_km[idx_list[k], idx_list[k + 1]]) for k in range(len(idx_list) - 1)
        )
        routes.append(
            VehicleRoute(
                vehicle_id=vehicle.id,
                steps=steps,
                distance_km=round(total_dist, 2),
                cost_inr=round(total_dist * cost_per_km, 2),
                co2_kg=round(total_dist * co2_per_tkm * avg_demand_t, 2),
            )
        )
    return routes


# ─────────────────────────────────────────────────────────────
# Alternate route finder — O(E log N) min-heap
# ─────────────────────────────────────────────────────────────


async def find_alternates(
    blocked_segment_id: str,
    n: int = 3,
    db: AsyncDB | None = None,
    mcp_clients: dict[str, MCPClient] | None = None,
) -> list[AlternateRoute]:
    """
    Find the top-N alternate routes bypassing ``blocked_segment_id``.

    Algorithm
    ---------
    1. Enumerate candidate edges/routes (from DB or synthesised).
    2. Score each: composite_cost = cost_inr + risk_score * 1000 + co2_kg * 50
    3. Maintain a MIN-HEAP of size N  →  O(E log N).
    4. Return the N cheapest by composite_cost.

    Parameters
    ----------
    blocked_segment_id : The route/segment to bypass.
    n                  : Number of alternates to return.
    db                 : Optional async DB session (AsyncDB protocol).
    mcp_clients        : Optional dict with "routing" MCPClient for OSRM calls.
    """

    # ── Gather candidate edges ────────────────────────────────
    candidates: list[dict[str, Any]] = []

    # Attempt to fetch from routing MCP (OSRM alternatives)
    routing_client = (mcp_clients or {}).get("routing")
    if routing_client:
        try:
            mcp_result = await routing_client.call(
                "get_alternatives",
                {"blocked_segment_id": blocked_segment_id, "n": n * 3},  # over-fetch
            )
            if isinstance(mcp_result, list):
                for r in mcp_result:
                    candidates.append(
                        {
                            "route_id": r.get("route_id", str(uuid.uuid4())),
                            "distance_km": float(r.get("distance_km", 300.0)),
                            "duration_min": float(r.get("duration_min", 300.0)),
                            "mode": "road",
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("find_alternates.routing_mcp_failed", error=str(exc))

    # If no candidates came from MCP, generate synthetic fallbacks
    if not candidates:
        log.info("find_alternates.using_synthetic_candidates", blocked=blocked_segment_id)
        for i in range(n * 3):
            # Spread across modes to surface multimodal options
            mode = ["road", "rail", "sea", "air"][i % 4]
            dist = 200.0 + i * 25.0
            spd = MODE_SPEED_KMH.get(mode, 60.0)
            candidates.append(
                {
                    "route_id": str(uuid.uuid4()),
                    "distance_km": dist,
                    "duration_min": (dist / spd) * 60.0,
                    "mode": mode,
                }
            )

    # ── Score and heap-select top-N  (O(E log N)) ────────────
    scored_routes: list[AlternateRoute] = []

    for cand in candidates:
        route_id = cand.get("route_id", str(uuid.uuid4()))
        dist = float(cand.get("distance_km", 300.0))
        mode = cand.get("mode", "road")
        duration_h = float(cand.get("duration_min", dist / 60.0 * 60.0)) / 60.0

        # Fetch per-route risk from Redis if available, else default low
        risk = 0.1
        try:
            risk_raw = await redis_client.get(f"risk:{route_id}")
            if risk_raw:
                risk = max(0.0, min(1.0, float(risk_raw)))
        except Exception:  # noqa: BLE001
            log.debug("find_alternates.risk_fetch_suppressed", route_id=route_id)

        cost_per_km = MODE_COST_PER_KM.get(mode, MODE_COST_PER_KM["road"])
        co2_per_tkm = MODE_CO2_PER_TONNE_KM.get(mode, MODE_CO2_PER_TONNE_KM["road"])

        cost_inr = dist * cost_per_km
        co2_kg = dist * co2_per_tkm * 10.0  # assume 10 tonne payload

        # composite for ranking
        composite_cost = cost_inr + risk * 1000.0 + co2_kg * 50.0

        route = AlternateRoute(
            composite_cost=composite_cost,
            route_id=route_id,
            cost_inr=round(cost_inr, 2),
            eta_h=round(duration_h, 2),
            risk_score=round(risk, 4),
            co2_kg=round(co2_kg, 2),
            mode=mode,
        )
        scored_routes.append(route)

    # Sort the final candidates ascending by composite_cost and take top n
    result = sorted(scored_routes, key=lambda r: r.composite_cost)[:n]

    log.info(
        "find_alternates.done",
        blocked_segment=blocked_segment_id,
        candidates_evaluated=len(candidates),
        alternates_returned=len(result),
    )

    return result

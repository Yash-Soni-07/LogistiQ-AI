import type { CoordinatePair } from "@/lib/cities";

export type RoutePoint = CoordinatePair;

// ── Coastal waypoints around India (all offshore, ordered NW → SW → SE → NE) ──
const COASTAL_NODES: RoutePoint[] = [
  [69.0, 22.5],  // Off Gujarat / Kandla
  [71.5, 19.8],  // Off Saurashtra
  [72.0, 18.5],  // Off Mumbai
  [72.8, 16.0],  // Off Ratnagiri
  [73.2, 15.2],  // Off Goa
  [74.0, 13.0],  // Off Mangalore
  [75.2, 10.5],  // Off Kochi approach
  [76.0, 8.5],   // Off Kerala tip
  [77.5, 7.0],   // Cape Comorin — southern tip
  [78.8, 8.2],   // Off Tuticorin
  [79.8, 10.5],  // Off Tamil Nadu
  [80.8, 13.2],  // Off Chennai
  [82.0, 15.5],  // Off Andhra
  [83.5, 17.8],  // Off Visakhapatnam
  [85.5, 19.8],  // Off Odisha
  [87.5, 21.0],  // Off Bengal
  [89.0, 21.8],  // Kolkata sea approach
];

// ── Major Indian ports (mapped to nearest COASTAL_NODES index) ──
const MAJOR_PORTS: { coords: RoutePoint; coastIdx: number }[] = [
  { coords: [70.13, 23.00], coastIdx: 0 },   // Kandla
  { coords: [72.88, 19.08], coastIdx: 2 },   // Mumbai
  { coords: [73.80, 15.40], coastIdx: 4 },   // Mormugao/Goa
  { coords: [74.80, 12.87], coastIdx: 5 },   // New Mangalore
  { coords: [76.27, 9.93],  coastIdx: 6 },   // Kochi
  { coords: [78.18, 8.80],  coastIdx: 9 },   // Tuticorin
  { coords: [80.27, 13.08], coastIdx: 11 },  // Chennai
  { coords: [83.22, 17.69], coastIdx: 13 },  // Visakhapatnam
  { coords: [87.20, 20.47], coastIdx: 15 },  // Paradip
  { coords: [88.05, 22.00], coastIdx: 16 },  // Kolkata/Haldia
];

// ── Utility functions ──

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function distance(a: RoutePoint, b: RoutePoint): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  return Math.sqrt(dx * dx + dy * dy);
}

function hashUnit(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return ((hash >>> 0) % 10000) / 10000;
}

function dedupePath(points: RoutePoint[]): RoutePoint[] {
  const deduped: RoutePoint[] = [];
  for (const point of points) {
    const prev = deduped[deduped.length - 1];
    if (!prev) {
      deduped.push(point);
      continue;
    }
    if (Math.abs(prev[0] - point[0]) > 1e-5 || Math.abs(prev[1] - point[1]) > 1e-5) {
      deduped.push(point);
    }
  }
  return deduped;
}

function linearPath(start: RoutePoint, end: RoutePoint, steps: number): RoutePoint[] {
  const pts: RoutePoint[] = [];
  const safeSteps = Math.max(2, steps);
  for (let i = 0; i < safeSteps; i += 1) {
    const t = i / (safeSteps - 1);
    pts.push([lerp(start[0], end[0], t), lerp(start[1], end[1], t)]);
  }
  return pts;
}

function cubicBezierPath(
  start: RoutePoint,
  control1: RoutePoint,
  control2: RoutePoint,
  end: RoutePoint,
  steps: number,
): RoutePoint[] {
  const pts: RoutePoint[] = [];
  const safeSteps = Math.max(3, steps);
  for (let i = 0; i < safeSteps; i += 1) {
    const t = i / (safeSteps - 1);
    const mt = 1 - t;
    const lon =
      mt * mt * mt * start[0] +
      3 * mt * mt * t * control1[0] +
      3 * mt * t * t * control2[0] +
      t * t * t * end[0];
    const lat =
      mt * mt * mt * start[1] +
      3 * mt * mt * t * control1[1] +
      3 * mt * t * t * control2[1] +
      t * t * t * end[1];
    pts.push([lon, lat]);
  }
  return pts;
}

// ── Catmull-Rom spline for smooth curves through ordered waypoints ──

function catmullRomSpline(waypoints: RoutePoint[], density: number = 8): RoutePoint[] {
  if (waypoints.length < 2) return [...waypoints];
  if (waypoints.length === 2) return linearPath(waypoints[0], waypoints[1], density);

  const result: RoutePoint[] = [];
  for (let i = 0; i < waypoints.length - 1; i++) {
    const p0 = waypoints[Math.max(0, i - 1)];
    const p1 = waypoints[i];
    const p2 = waypoints[i + 1];
    const p3 = waypoints[Math.min(waypoints.length - 1, i + 2)];

    for (let j = 0; j < density; j++) {
      const t = j / density;
      const t2 = t * t;
      const t3 = t2 * t;
      result.push([
        0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
        0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
      ]);
    }
  }
  result.push(waypoints[waypoints.length - 1]);
  return result;
}

// ── Port & coastal helpers ──

function nearestPort(point: RoutePoint): { coords: RoutePoint; coastIdx: number } {
  let best = MAJOR_PORTS[0];
  let bestDist = Infinity;
  for (const port of MAJOR_PORTS) {
    const d = distance(point, port.coords);
    if (d < bestDist) {
      bestDist = d;
      best = port;
    }
  }
  return best;
}

function getCoastalSegment(startIdx: number, endIdx: number): RoutePoint[] {
  const lo = Math.min(startIdx, endIdx);
  const hi = Math.max(startIdx, endIdx);
  const segment = COASTAL_NODES.slice(lo, hi + 1);
  return startIdx <= endIdx ? segment : [...segment].reverse();
}

// ── Route builders ──

function buildRoadPath(origin: RoutePoint, destination: RoutePoint, seedKey: string): RoutePoint[] {
  const dx = destination[0] - origin[0];
  const dy = destination[1] - origin[1];
  const len = Math.max(0.001, Math.sqrt(dx * dx + dy * dy));
  const nx = -dy / len;
  const ny = dx / len;
  const seed = hashUnit(seedKey);
  const signed = (seed - 0.5) * 2;
  const bend = clamp(len * 0.12, 0.25, 2.4) * signed;

  const c1: RoutePoint = [origin[0] + dx * 0.30 + nx * bend, origin[1] + dy * 0.30 + ny * bend];
  const c2: RoutePoint = [
    origin[0] + dx * 0.72 - nx * bend * 0.65,
    origin[1] + dy * 0.72 - ny * bend * 0.65,
  ];

  return dedupePath(cubicBezierPath(origin, c1, c2, destination, 40));
}

function buildSeaPath(origin: RoutePoint, destination: RoutePoint, _seedKey: string): RoutePoint[] {
  const startPort = nearestPort(origin);
  const endPort = nearestPort(destination);

  // Inland leg: origin → nearest port (straight line, simulates truck to port)
  const inlandA = linearPath(origin, startPort.coords, 6);

  // Sea leg: port → coastal waypoints → port (Catmull-Rom through offshore nodes)
  const coastalWaypoints = getCoastalSegment(startPort.coastIdx, endPort.coastIdx);
  const seaControlPoints = [startPort.coords, ...coastalWaypoints, endPort.coords];
  const seaLeg = seaControlPoints.length > 2
    ? catmullRomSpline(seaControlPoints, 10)
    : linearPath(seaControlPoints[0], seaControlPoints[seaControlPoints.length - 1], 20);

  // Inland leg: port → destination
  const inlandB = linearPath(endPort.coords, destination, 6);

  return dedupePath([...inlandA, ...seaLeg, ...inlandB]);
}

export function buildFallbackRoutePath(
  mode: "road" | "rail" | "sea" | "air" | "multimodal",
  origin: RoutePoint,
  destination: RoutePoint,
  routeKey: string,
): RoutePoint[] {
  if (mode === "sea") {
    return buildSeaPath(origin, destination, routeKey);
  }
  if (mode === "air") {
    return linearPath(origin, destination, 28);
  }
  return buildRoadPath(origin, destination, routeKey);
}

export function slicePathByProgress(
  path: RoutePoint[],
  progress: number,
  current: RoutePoint,
): RoutePoint[] {
  if (path.length < 2) {
    return [current];
  }

  const clamped = clamp(progress, 0, 1);
  const scaled = clamped * (path.length - 1);
  const whole = Math.floor(scaled);
  const frac = scaled - whole;

  const travelled: RoutePoint[] = path.slice(0, whole + 1);

  if (whole + 1 < path.length) {
    const start = path[whole];
    const end = path[whole + 1];
    travelled.push([lerp(start[0], end[0], frac), lerp(start[1], end[1], frac)]);
  }

  const last = travelled[travelled.length - 1];
  if (!last || Math.abs(last[0] - current[0]) > 1e-5 || Math.abs(last[1] - current[1]) > 1e-5) {
    travelled.push(current);
  }

  return dedupePath(travelled);
}

function isCoordinatePair(value: unknown): value is [number, number] {
  return (
    Array.isArray(value) &&
    value.length >= 2 &&
    typeof value[0] === "number" &&
    Number.isFinite(value[0]) &&
    typeof value[1] === "number" &&
    Number.isFinite(value[1])
  );
}

export function parseRoutingGeometryCoordinates(geometry: unknown): RoutePoint[] {
  if (!geometry || typeof geometry !== "object") {
    return [];
  }

  const coordinates = (geometry as { coordinates?: unknown }).coordinates;
  if (!Array.isArray(coordinates)) {
    return [];
  }

  const parsed: RoutePoint[] = [];
  for (const coordinate of coordinates) {
    if (!isCoordinatePair(coordinate)) {
      continue;
    }
    parsed.push([coordinate[0], coordinate[1]]);
  }

  return dedupePath(parsed);
}

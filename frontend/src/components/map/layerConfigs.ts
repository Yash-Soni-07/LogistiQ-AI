import type { Layer } from "@deck.gl/core";
import { ArcLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import { PathStyleExtension } from "@deck.gl/extensions";
import type { CoordinatePair } from "@/lib/cities";
import { slicePathByProgress } from "./routeGeometry";

export type FreightMode = "road" | "air" | "sea" | "rail" | "multimodal";

export interface FreightRenderPoint {
  shipmentId: string;
  mode: FreightMode;
  origin: CoordinatePair;
  destination: CoordinatePair;
  current: CoordinatePair;
  progress: number;
  routePath: CoordinatePair[];
}

export interface FireMarker {
  position: CoordinatePair; // [lon, lat]
  description: string;
  eventId: string;
}

/** VRP route overlay shown after fire simulation — alternate routes in green, blocked in red */
export interface VRPOverlay {
  affectedShipmentId: string | null;
  fireProgress: number; // 0–1, used to slice the blocked segment
  alternateRoutes: { routeId: string; geometry: [number, number][] }[];
}

export function buildFireLayer(markers: FireMarker[]): Layer[] {
  if (!markers || markers.length === 0) return [];
  const updateKey = markers.map((m) => m.eventId).join("|");
  return [
    // Outer pulse ring (large, very transparent red)
    new ScatterplotLayer<FireMarker>({
      id: "fire-glow-ring",
      data: markers,
      getPosition: (d) => d.position,
      getRadius: 35000,
      radiusMinPixels: 20,
      radiusMaxPixels: 60,
      getFillColor: [255, 60, 10, 30],
      stroked: false,
      filled: true,
      updateTriggers: { getPosition: updateKey },
    }),
    // Mid ring (semi-transparent amber)
    new ScatterplotLayer<FireMarker>({
      id: "fire-mid-ring",
      data: markers,
      getPosition: (d) => d.position,
      getRadius: 18000,
      radiusMinPixels: 12,
      radiusMaxPixels: 32,
      getFillColor: [255, 120, 30, 70],
      getLineColor: [255, 80, 10, 180],
      lineWidthMinPixels: 2,
      stroked: true,
      filled: true,
      updateTriggers: { getPosition: updateKey },
    }),
    // Core bright dot (solid orange-red)
    new ScatterplotLayer<FireMarker>({
      id: "fire-core-dot",
      data: markers,
      getPosition: (d) => d.position,
      getRadius: 8000,
      radiusMinPixels: 7,
      radiusMaxPixels: 18,
      getFillColor: [255, 180, 30, 255],
      getLineColor: [220, 40, 10, 255],
      lineWidthMinPixels: 2.5,
      stroked: true,
      filled: true,
      updateTriggers: { getPosition: updateKey },
    }),
  ];
}

interface SurfacePathDatum {
  shipmentId: string;
  mode: FreightMode;
  path: CoordinatePair[];
}

// ── Color palette ──
const ROAD_COLOR: [number, number, number, number] = [139, 92, 246, 240];
const SEA_COLOR: [number, number, number, number] = [14, 165, 233, 240];
const AIR_COLOR: [number, number, number, number] = [236, 72, 153, 240];
const RAIL_COLOR: [number, number, number, number] = [16, 185, 129, 240];

const ROAD_GLOW: [number, number, number, number] = [139, 92, 246, 50];
const SEA_GLOW: [number, number, number, number] = [14, 165, 233, 45];
const AIR_GLOW: [number, number, number, number] = [236, 72, 153, 35];

function modeColor(mode: FreightMode): [number, number, number, number] {
  if (mode === "sea") return SEA_COLOR;
  if (mode === "air") return AIR_COLOR;
  if (mode === "rail") return RAIL_COLOR;
  return ROAD_COLOR;
}

function modeGlow(mode: FreightMode): [number, number, number, number] {
  if (mode === "sea") return SEA_GLOW;
  if (mode === "air") return AIR_GLOW;
  return ROAD_GLOW;
}

function modeWidth(mode: FreightMode): number {
  if (mode === "air") return 4.5;
  if (mode === "sea") return 3.5;
  return 3.8;
}

// ── Freight Layers: Air, Sea, Road, and Rail ─────────────────────────────────
export function buildFreightLayers(points: FreightRenderPoint[], runId = 0): Layer[] {
  const airPoints = points.filter((p) => p.mode === "air");
  const seaPoints = points.filter((p) => p.mode === "sea");
  const roadRailPoints = points.filter((p) => p.mode !== "air" && p.mode !== "sea");

  // ── Surface path data ──
  const buildPathDatum = (p: FreightRenderPoint): SurfacePathDatum => ({
    shipmentId: p.shipmentId,
    mode: p.mode,
    path: p.routePath.length > 1 ? p.routePath : [p.origin, p.destination],
  });

  const buildTravelledDatum = (p: FreightRenderPoint): SurfacePathDatum => ({
    shipmentId: p.shipmentId,
    mode: p.mode,
    path: slicePathByProgress(
      p.routePath.length > 1 ? p.routePath : [p.origin, p.destination],
      p.progress,
      p.current,
    ),
  });

  const seaPlanned = seaPoints.map(buildPathDatum);
  const seaTravelled = seaPoints.map(buildTravelledDatum);
  const roadPlanned = roadRailPoints.map(buildPathDatum);
  const roadTravelled = roadRailPoints.map(buildTravelledDatum);

  const updateKey = points
    .map((p) => `${p.shipmentId}:${p.progress.toFixed(4)}`)
    .join("|");

  return [
    // ━━━ AIR: Full planned arc (ghosted) ━━━
    new ArcLayer<FreightRenderPoint>({
      id: `freight-air-arcs-planned-${runId}`,
      data: airPoints,
      getSourcePosition: (d) => d.origin,
      getTargetPosition: (d) => d.destination,
      getSourceColor: [139, 148, 255, 60],
      getTargetColor: [139, 148, 255, 60],
      getHeight: () => 0.6,
      getWidth: 2,
      widthMinPixels: 1,
      widthMaxPixels: 4,
      greatCircle: true,
      numSegments: 100,
      getTilt: (d) => ((d.shipmentId.charCodeAt(0) % 5) - 2) * 5,
      updateTriggers: { getSourcePosition: updateKey, getTargetPosition: updateKey },
    }),

    // ━━━ AIR: Progress arc (bright, animated) ━━━
    new ArcLayer<FreightRenderPoint>({
      id: `freight-air-arcs-progress-${runId}`,
      data: airPoints,
      getSourcePosition: (d) => d.origin,
      getTargetPosition: (d) => d.current,
      getSourceColor: [120, 130, 255, 140],
      getTargetColor: [180, 185, 255, 255],
      getHeight: () => 0.6,
      getWidth: 3,
      widthMinPixels: 2,
      widthMaxPixels: 6,
      greatCircle: true,
      numSegments: 80,
      getTilt: (d) => ((d.shipmentId.charCodeAt(0) % 5) - 2) * 5,
      updateTriggers: { getTargetPosition: updateKey },
      transitions: { getTargetPosition: 700 },
    }),

    // ━━━ AIR: Glow arc underneath ━━━
    new ArcLayer<FreightRenderPoint>({
      id: `freight-air-arcs-glow-${runId}`,
      data: airPoints,
      getSourcePosition: (d) => d.origin,
      getTargetPosition: (d) => d.current,
      getSourceColor: AIR_GLOW,
      getTargetColor: AIR_GLOW,
      getHeight: () => 0.6,
      getWidth: 8,
      widthMinPixels: 4,
      widthMaxPixels: 14,
      greatCircle: true,
      numSegments: 80,
      getTilt: (d) => ((d.shipmentId.charCodeAt(0) % 5) - 2) * 5,
      updateTriggers: { getTargetPosition: updateKey },
      transitions: { getTargetPosition: 700 },
    }),

    // ━━━ SEA: Glow underlayer ━━━
    new PathLayer<SurfacePathDatum>({
      id: `freight-sea-glow-${runId}`,
      data: seaPlanned,
      getPath: (d) => d.path,
      getColor: SEA_GLOW,
      getWidth: 8,
      widthUnits: "pixels",
      widthMinPixels: 2,
      widthMaxPixels: 10,
      capRounded: true,
      jointRounded: true,
      billboard: true,
      updateTriggers: { getPath: updateKey },
    }),

    // ━━━ SEA: Planned route (dashed) ━━━
    new PathLayer<SurfacePathDatum>({
      id: `freight-sea-routes-planned-${runId}`,
      data: seaPlanned,
      getPath: (d) => d.path,
      getColor: [34, 211, 238, 90],
      getWidth: 3,
      widthUnits: "pixels",
      widthMinPixels: 2,
      widthMaxPixels: 5,
      capRounded: true,
      jointRounded: true,
      billboard: true,
      extensions: [new PathStyleExtension({ dash: true })],
      ...({ getDashArray: [8, 6] } as Record<string, unknown>),
      updateTriggers: { getPath: updateKey },
    }),

    // ━━━ SEA: Travelled progress (solid bright) ━━━
    new PathLayer<SurfacePathDatum>({
      id: `freight-sea-routes-progress-${runId}`,
      data: seaTravelled,
      getPath: (d) => d.path,
      getColor: SEA_COLOR,
      getWidth: 4,
      widthUnits: "pixels",
      widthMinPixels: 3,
      widthMaxPixels: 7,
      capRounded: true,
      jointRounded: true,
      billboard: true,
      updateTriggers: { getPath: updateKey },
      transitions: { getPath: 700 },
    }),

    // ━━━ ROAD: Glow underlayer ━━━
    new PathLayer<SurfacePathDatum>({
      id: `freight-road-glow-${runId}`,
      data: roadPlanned,
      getPath: (d) => d.path,
      getColor: (d) => modeGlow(d.mode),
      getWidth: 7,
      widthUnits: "pixels",
      widthMinPixels: 2,
      widthMaxPixels: 10,
      capRounded: true,
      jointRounded: true,
      billboard: true,
      updateTriggers: { getPath: updateKey },
    }),

    // ━━━ ROAD: Planned route (ghosted solid) ━━━
    new PathLayer<SurfacePathDatum>({
      id: `freight-road-routes-planned-${runId}`,
      data: roadPlanned,
      getPath: (d) => d.path,
      getColor: (d) => {
        const c = modeColor(d.mode);
        return [c[0], c[1], c[2], 80];
      },
      getWidth: (d) => modeWidth(d.mode),
      widthUnits: "pixels",
      widthMinPixels: 1,
      widthMaxPixels: 5,
      capRounded: true,
      jointRounded: true,
      billboard: true,
      updateTriggers: { getPath: updateKey },
    }),

    // ━━━ ROAD: Travelled progress (bright solid) ━━━
    new PathLayer<SurfacePathDatum>({
      id: `freight-road-routes-progress-${runId}`,
      data: roadTravelled,
      getPath: (d) => d.path,
      getColor: (d) => modeColor(d.mode),
      getWidth: (d) => modeWidth(d.mode) + 1,
      widthUnits: "pixels",
      widthMinPixels: 2,
      widthMaxPixels: 7,
      capRounded: true,
      jointRounded: true,
      billboard: true,
      updateTriggers: { getPath: updateKey },
      transitions: { getPath: 700 },
    }),

    // ━━━ MARKERS: Origin points (small, muted) ━━━
    new ScatterplotLayer<FreightRenderPoint>({
      id: `freight-origin-points-${runId}`,
      data: points,
      getPosition: (d) => d.origin,
      getRadius: 4500,
      radiusMinPixels: 3,
      radiusMaxPixels: 7,
      getFillColor: [100, 116, 139, 120],
      getLineColor: [148, 163, 184, 180],
      lineWidthMinPixels: 1,
      stroked: true,
      filled: true,
      pickable: false,
    }),

    // ━━━ MARKERS: Destination points ━━━
    new ScatterplotLayer<FreightRenderPoint>({
      id: `freight-destination-points-${runId}`,
      data: points,
      getPosition: (d) => d.destination,
      getRadius: 5000,
      radiusMinPixels: 3,
      radiusMaxPixels: 8,
      getFillColor: [248, 250, 252, 180],
      getLineColor: [148, 163, 184, 220],
      lineWidthMinPixels: 1,
      stroked: true,
      filled: true,
      pickable: false,
    }),

    // ━━━ MARKERS: Live vehicle glow ring ━━━
    new ScatterplotLayer<FreightRenderPoint>({
      id: `freight-live-glow-${runId}`,
      data: points,
      getPosition: (d) => d.current,
      getRadius: 14000,
      radiusMinPixels: 6,
      radiusMaxPixels: 22,
      getFillColor: (d) => {
        const c = modeColor(d.mode);
        return [c[0], c[1], c[2], 40];
      },
      stroked: false,
      filled: true,
      updateTriggers: { getPosition: updateKey },
      transitions: { getPosition: 700 },
    }),

    // ━━━ MARKERS: Live vehicle dot ━━━
    new ScatterplotLayer<FreightRenderPoint>({
      id: `freight-live-points-${runId}`,
      data: points,
      getPosition: (d) => d.current,
      getRadius: 8000,
      radiusMinPixels: 7,
      radiusMaxPixels: 18,
      getFillColor: (d) => modeColor(d.mode),
      getLineColor: [255, 255, 255, 220],
      lineWidthMinPixels: 1.5,
      stroked: true,
      filled: true,
      updateTriggers: { getPosition: updateKey },
      transitions: { getPosition: 700 },
    }),
  ];
}

// ── VRP Overlay: alternate routes (green) + blocked segment (red) ────────────────
export function buildVRPLayers(
  overlay: VRPOverlay | null,
  points: FreightRenderPoint[],
): Layer[] {
  if (!overlay || overlay.alternateRoutes.length === 0) return [];

  const layers: Layer[] = [];

  // Red layer: remaining (untraversed + blocked) segment of affected shipment
  const affected = points.find((p) => p.shipmentId === overlay.affectedShipmentId);
  if (affected && affected.routePath.length > 1) {
    // Compute remaining path: from current progress index to end
    const n = affected.routePath.length;
    const scaled = affected.progress * (n - 1);
    const startIdx = Math.floor(scaled);
    const remaining: [number, number][] = [
      affected.current as [number, number],
      ...(affected.routePath.slice(startIdx + 1) as [number, number][]),
    ];
    if (remaining.length > 1) {
      layers.push(
        new PathLayer<{ path: [number, number][] }>({
          id: "vrp-blocked-route",
          data: [{ path: remaining as [number, number][] }],
          getPath: (d) => d.path,
          getWidth: 5,
          widthMinPixels: 3,
          widthMaxPixels: 8,
          getColor: [239, 68, 68, 210],  // red-500
          rounded: true,
          capRounded: true,
          jointRounded: true,
          extensions: [new PathStyleExtension({ dash: true })],
          ...({ getDashArray: [8, 5] } as Record<string, unknown>),
        }),
      );
    }
  }

  // Green layers: alternate OSRM routes
  const GREENS: [number, number, number, number][] = [
    [34, 197, 94, 230],  // green-500
    [16, 185, 129, 200], // emerald-500
  ];
  overlay.alternateRoutes.forEach((alt, i) => {
    if (alt.geometry.length < 2) return;
    layers.push(
      new PathLayer<{ path: [number, number][] }>({
        id: `vrp-alt-route-${i}`,
        data: [{ path: alt.geometry }],
        getPath: (d) => d.path,
        getWidth: 5,
        widthMinPixels: 3,
        widthMaxPixels: 8,
        getColor: GREENS[i] ?? GREENS[0],
        rounded: true,
        capRounded: true,
        jointRounded: true,
      }),
    );
  });

  return layers;
}

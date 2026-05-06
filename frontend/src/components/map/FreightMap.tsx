import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { Navigation } from "lucide-react";
import { Map as MapGL, type MapRef } from "react-map-gl/maplibre";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { buildFreightLayers, buildFireLayer, buildVRPLayers, type FireMarker, type FreightMode, type FreightRenderPoint, type VRPOverlay } from "./layerConfigs";
import { buildFallbackRoutePath, parseRoutingGeometryCoordinates } from "./routeGeometry";
import { resolveCityCoords, type CoordinatePair } from "@/lib/cities";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuthStore } from "@/stores/auth.store";
import { useSimulationStore } from "@/stores/simulation.store";
import { useThemeStore } from "@/stores/theme.store";
import "maplibre-gl/dist/maplibre-gl.css";

// ── Stadia Maps style URLs ────────────────────────────────────────────────────
// VITE_STADIA_MAPS_STYLE is a full dark-mode URL that may include ?api_key=...
// We extract just the key and apply it to BOTH dark and light style URLs so
// the theme toggle works correctly while still authenticating with Stadia.
const _stadiaEnv = (import.meta.env.VITE_STADIA_MAPS_STYLE as string | undefined) ?? "";
const _keyMatch  = _stadiaEnv.match(/[?&]api_key=([^&]+)/);
const _keyParam  = _keyMatch ? `?api_key=${_keyMatch[1]}` : "";
const STADIA_DARK  = `https://tiles.stadiamaps.com/styles/alidade_smooth_dark.json${_keyParam}`;
const STADIA_LIGHT = `https://tiles.stadiamaps.com/styles/alidade_smooth.json${_keyParam}`;

interface SimulationShipmentPayload {
  shipment_id?: string;
  mode?: string;
  origin?: string;
  destination?: string;
  origin_lon?: number;
  origin_lat?: number;
  destination_lon?: number;
  destination_lat?: number;
  current_lon?: number;
  current_lat?: number;
  progress?: number;
  route_path?: unknown;
}

interface SimulationBatchPayload {
  type?: string;
  shipments?: SimulationShipmentPayload[];
}

interface FeatureCollectionPayload {
  type: "FeatureCollection";
  features: Array<{
    geometry?: { coordinates?: [number, number] };
    properties?: {
      shipment_id?: string;
      mode?: string;
      origin?: string;
      destination?: string;
      current_lon?: number;
      current_lat?: number;
    };
  }>;
}

interface RoutingToolEnvelope {
  result?: {
    geometry?: unknown;
  };
}

function isFeatureCollectionPayload(raw: unknown): raw is FeatureCollectionPayload {
  return Boolean(
    raw &&
      typeof raw === "object" &&
      (raw as { type?: unknown }).type === "FeatureCollection" &&
      Array.isArray((raw as { features?: unknown }).features),
  );
}

function normalizeMode(rawMode: string | undefined): FreightMode {
  if (rawMode === "air" || rawMode === "sea" || rawMode === "road" || rawMode === "rail") {
    return rawMode;
  }
  return "road";
}

function mergePoints(
  current: FreightRenderPoint[],
  incoming: FreightRenderPoint[],
): FreightRenderPoint[] {
  const byId = new Map(current.map((point) => [point.shipmentId, point]));
  for (const point of incoming) {
    const previous = byId.get(point.shipmentId);
    byId.set(
      point.shipmentId,
      previous
        ? {
            ...previous,
            ...point,
            routePath: point.routePath.length > 1 ? point.routePath : previous.routePath,
          }
        : point,
    );
  }
  return Array.from(byId.values());
}

function getBackendOrigin(): string {
  const raw = (import.meta.env.VITE_API_URL as string | undefined)?.trim() || "http://localhost:8000/api/v1";
  try {
    return new URL(raw).origin;
  } catch {
    return "http://localhost:8000";
  }
}

function toRoutingCoord(coord: CoordinatePair): string {
  return `${coord[1].toFixed(6)},${coord[0].toFixed(6)}`;
}

function isCoordPair(value: unknown): value is CoordinatePair {
  return (
    Array.isArray(value) &&
    value.length >= 2 &&
    typeof value[0] === "number" &&
    Number.isFinite(value[0]) &&
    typeof value[1] === "number" &&
    Number.isFinite(value[1])
  );
}

function resolveDestinationCoords(payload: SimulationShipmentPayload): CoordinatePair {
  if (typeof payload.destination_lon === "number" && typeof payload.destination_lat === "number") {
    return [payload.destination_lon, payload.destination_lat];
  }
  return resolveCityCoords(payload.destination ?? "");
}

function resolveOriginCoords(payload: SimulationShipmentPayload): CoordinatePair {
  if (typeof payload.origin_lon === "number" && typeof payload.origin_lat === "number") {
    return [payload.origin_lon, payload.origin_lat];
  }
  return resolveCityCoords(payload.origin ?? "");
}

export default function FreightMap() {
  const [points, setPoints] = useState<FreightRenderPoint[]>([]);
  const [runId, setRunId] = useState(0);
  const [fireMarkers, setFireMarkers] = useState<FireMarker[]>([]);
  const [vrpOverlay, setVrpOverlay] = useState<VRPOverlay | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const mapRef = useRef<MapRef | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const routeRequestInFlight = useRef<Set<string>>(new Set());
  const backendOrigin = useMemo(() => getBackendOrigin(), []);

  // ── Map style: isDark from Zustand (set by ThemeToggle) drives tile selection ──
  const { isDark } = useThemeStore();
  const mapStyle = isDark ? STADIA_DARK : STADIA_LIGHT;

  // Filter visible points by user-selected transport modes
  const { visibleModes } = useSimulationStore();
  const visiblePoints = useMemo(
    () => points.filter((p) => visibleModes.includes(p.mode as any)),
    [points, visibleModes],
  );

  const layers = useMemo(
    () => [
      ...buildFreightLayers(visiblePoints, runId),
      ...buildFireLayer(fireMarkers),
      ...buildVRPLayers(vrpOverlay, visiblePoints),
    ],
    [visiblePoints, fireMarkers, vrpOverlay, runId],
  );

  const modeCounts = useMemo(() => {
    const counts = { road: 0, air: 0, sea: 0, rail: 0 };
    for (const point of visiblePoints) {
      if (point.mode === "air") counts.air += 1;
      else if (point.mode === "sea") counts.sea += 1;
      else if (point.mode === "rail") counts.rail += 1;
      else counts.road += 1;
    }
    return counts;
  }, [visiblePoints]);

  // ── VRP results: draw alternate routes (green) + blocked segment (red) on map ──
  useWebSocket("vrp-results", (msg: unknown) => {
    if (!msg || typeof msg !== "object") return;
    const m = msg as Record<string, unknown>;
    if (m.type === "pong" || m.type === "heartbeat") return;
    if (m.disruption || m.alternate_routes) {
      const disruption = m.disruption as Record<string, unknown>;
      const altRoutes = m.alternate_routes as Record<string, unknown[]>;
      const routes = Object.values(altRoutes ?? {}).flat() as any[];
      setVrpOverlay({
        affectedShipmentId: (disruption?.shipment_id as string) ?? null,
        fireProgress: 0, // will be inferred from fire marker position
        alternateRoutes: routes
          .filter((r: any) => Array.isArray(r.geometry) && r.geometry.length > 1)
          .slice(0, 2)
          .map((r: any, i: number) => ({
            routeId: r.route_id ?? `alt-${i}`,
            geometry: r.geometry as [number, number][],
          })),
      });
    }
  });

  const { isConnected } = useWebSocket("shipments", (message: unknown) => {
    // Handle special event types before generic processing
    if (message && typeof message === "object") {
      const msg = message as Record<string, unknown>;

      // ── Fire event: show pulsing fire marker on the map ──
      if (msg.type === "fire_event") {
        const lon = Number(msg.fire_lon);
        const lat = Number(msg.fire_lat);
        if (!isNaN(lon) && !isNaN(lat) && lon !== 0 && lat !== 0) {
          setFireMarkers([{
            position: [lon, lat],
            description: (msg.description as string) ?? "Fire disruption",
            eventId: (msg.event_id as string) ?? `fire-${Date.now()}`,
          }]);
        }
        return;
      }

      // ── Truck arrived at fire location ──
      if (msg.type === "truck_at_fire") {
        import("sonner").then(({ toast }) => {
          toast.warning(
            `🚨 Truck stopped at fire zone! ${msg.origin} → ${msg.destination} — awaiting reroute decision.`,
            { duration: Infinity, id: "truck-at-fire" },
          );
        });
        return;
      }

      // ── Fire cleared: remove fire marker and VRP overlay ──
      if (msg.type === "fire_cleared") {
        setFireMarkers([]);
        setVrpOverlay(null);
        import("sonner").then(({ toast }) => { toast.dismiss("truck-at-fire"); });
        return;
      }

      // ── Simulation started: hard-reset map points but KEEP fire marker
      // (fire should persist until user reroutes, not disappear on tick restart)
      if (msg.type === "simulation_started") {
        // fall-through so the batch handler populates the 3 points
      }
    }

    if (isFeatureCollectionPayload(message)) {
      const fromFeatures: FreightRenderPoint[] = message.features
        .map((feature) => {
          const properties = feature.properties ?? {};
          const shipmentId = properties.shipment_id;
          if (!shipmentId) {
            return null;
          }

          const mode = normalizeMode(properties.mode);
          const origin = resolveCityCoords(properties.origin ?? "");
          const destination = resolveCityCoords(properties.destination ?? "");
          const featureCoords = feature.geometry?.coordinates;
          const currentCoords: CoordinatePair =
            Array.isArray(featureCoords) &&
            typeof featureCoords[0] === "number" &&
            typeof featureCoords[1] === "number"
              ? [featureCoords[0], featureCoords[1]]
              : typeof properties.current_lon === "number" && typeof properties.current_lat === "number"
                ? [properties.current_lon, properties.current_lat]
                : origin;

          return {
            shipmentId,
            mode,
            origin,
            destination,
            current: currentCoords,
            progress: 0,
            routePath: buildFallbackRoutePath(mode, origin, destination, `${shipmentId}:${mode}:initial`),
          } satisfies FreightRenderPoint;
        })
        .filter((point): point is FreightRenderPoint => point !== null);

      setPoints((prev) => mergePoints(prev, fromFeatures));
      return;
    }

    if (!message || typeof message !== "object") {
      return;
    }

    const batch = message as SimulationBatchPayload;
    if (!Array.isArray(batch.shipments)) {
      return;
    }

    // On simulation_started: replace all points with the new 3 demo shipments
    const isReset = batch.type === "simulation_started";

    const nextPoints: FreightRenderPoint[] = batch.shipments
      .map((shipment) => {
        if (
          !shipment.shipment_id ||
          typeof shipment.current_lon !== "number" ||
          typeof shipment.current_lat !== "number"
        ) {
          return null;
        }

        const mode = normalizeMode(shipment.mode);
        const origin = resolveOriginCoords(shipment);
        const destination = resolveDestinationCoords(shipment);
        const serverPath = Array.isArray(shipment.route_path)
          ? (shipment.route_path.filter((point) => isCoordPair(point)) as CoordinatePair[])
          : [];

        return {
          shipmentId: shipment.shipment_id,
          mode,
          origin,
          destination,
          current: [shipment.current_lon, shipment.current_lat],
          progress: typeof shipment.progress === "number" ? shipment.progress : 0,
          routePath:
            serverPath.length > 1
              ? serverPath
              : buildFallbackRoutePath(mode, origin, destination, `${shipment.shipment_id}:${mode}:tick`),
        } satisfies FreightRenderPoint;
      })
      .filter((point): point is FreightRenderPoint => point !== null);

    if (nextPoints.length > 0) {
      if (isReset) {
        // Hard reset: increment runId so Deck.GL destroys old layers (cancels transitions)
        setRunId((r) => r + 1);
        setPoints(nextPoints);
      } else {
        setPoints((prev) => mergePoints(prev, nextPoints));
      }
    }
  });

  useEffect(() => {
    if (points.length === 0) {
      return;
    }

    const updatable = points.filter(
      (point) => (point.mode === "road" || point.mode === "rail") && point.routePath.length < 4,
    );

    if (updatable.length === 0) {
      return;
    }

    let cancelled = false;

    const hydrateRoadPaths = async () => {
      const auth = useAuthStore.getState();
      if (!auth.token) {
        return;
      }

      for (const point of updatable) {
        const requestKey = `${point.shipmentId}:${point.mode}`;
        if (routeRequestInFlight.current.has(requestKey)) {
          continue;
        }

        routeRequestInFlight.current.add(requestKey);
        try {
          const response = await axios.post<RoutingToolEnvelope>(
            `${backendOrigin}/mcp/routing/call/get_route`,
            {
              params: {
                origin_id: toRoutingCoord(point.origin),
                dest_id: toRoutingCoord(point.destination),
                avoid_segments: [],
              },
              tenant_id: auth.tenant?.id ?? undefined,
            },
            {
              timeout: 9000,
              headers: {
                Authorization: `Bearer ${auth.token}`,
                ...(auth.tenant?.id ? { "X-Tenant-ID": auth.tenant.id } : {}),
              },
            },
          );

          const parsed = parseRoutingGeometryCoordinates(response.data?.result?.geometry);
          if (cancelled || parsed.length < 4) {
            continue;
          }

          setPoints((prev) =>
            prev.map((item) => (item.shipmentId === point.shipmentId ? { ...item, routePath: parsed } : item)),
          );
        } catch {
          // keep deterministic local fallback path
        } finally {
          routeRequestInFlight.current.delete(requestKey);
        }
      }
    };

    void hydrateRoadPaths();

    return () => {
      cancelled = true;
    };
  }, [backendOrigin, points]);

  useEffect(() => {
    if (!mapReady || !mapRef.current || overlayRef.current) {
      return;
    }

    const map = mapRef.current.getMap();
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(overlay);
    overlayRef.current = overlay;

    return () => {
      map.removeControl(overlay);
      overlayRef.current = null;
    };
  }, [mapReady]);

  useEffect(() => {
    if (overlayRef.current) {
      overlayRef.current.setProps({ layers });
    }
  }, [layers]);

  return (
    <div className="absolute inset-0">
      <MapGL
        ref={mapRef}
        initialViewState={{ longitude: 79.4, latitude: 22.2, zoom: 5.4, pitch: 48, bearing: -6 }}
        mapStyle={mapStyle}
        interactive
        dragPan
        scrollZoom
        style={{ width: "100%", height: "100%" }}
        onLoad={() => setMapReady(true)}
      />

      <div className="absolute top-4 left-4 bg-[var(--lq-surface)]/85 backdrop-blur-md px-3 py-1.5 rounded border border-[var(--lq-border)] text-[var(--lq-text-bright)] text-xs font-semibold shadow-sm pointer-events-none flex items-center gap-2">
        <Navigation size={12} className="text-[var(--lq-cyan)]" />
        Realtime Freight Simulation
      </div>

      <div className="absolute top-4 right-4 bg-[var(--lq-surface)]/85 backdrop-blur-md px-3 py-1.5 rounded border border-[var(--lq-border)] text-[var(--lq-text-bright)] text-[11px] font-semibold shadow-sm pointer-events-none">
        {isConnected ? "Live Stream Connected" : "Connecting to Live Stream"}
      </div>

      <div className="absolute bottom-4 left-4 bg-[var(--lq-surface)]/88 backdrop-blur-md px-3 py-2 rounded border border-[var(--lq-border)] shadow-sm pointer-events-none">
        <div className="flex items-center gap-4 text-[11px] font-semibold text-[var(--lq-text-bright)]">
          <div className="flex items-center gap-1.5">
            <span className="inline-block size-2 rounded-full bg-[rgb(129,140,248)]" />
            Air {modeCounts.air}
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block size-2 rounded-full bg-[rgb(56,189,248)]" />
            Road {modeCounts.road}
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block size-2 rounded-full bg-[rgb(34,211,238)]" />
            Sea {modeCounts.sea}
          </div>
        </div>
      </div>
    </div>
  );
}

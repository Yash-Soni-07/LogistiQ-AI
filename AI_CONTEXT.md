# LogistiQ AI — Project Context

> Feed this file to any AI assistant to get full project context instantly.
> Last updated: 2026-04-23

---

## 1. Project Overview

**LogistiQ AI** is a production-grade, multi-tenant AI-powered freight intelligence platform targeting Indian logistics operators. It provides real-time shipment tracking, geospatial disruption alerts (floods, fires, earthquakes, strikes), autonomous rerouting via AI agents, and a natural-language "Copilot" interface.

**Monorepo layout:**
```
logistiq-ai/
├── backend/          # Python FastAPI (async)
├── frontend/         # React + Vite + TypeScript
├── docker-compose.yml
├── docs/
├── infra/
└── AI_CONTEXT.md     ← this file
```

---

## 2. Dev Environment

### Starting Services
```powershell
# Infrastructure (PostgreSQL + Redis)
docker-compose up -d

# Backend — ALWAYS use uv run (not plain python/uvicorn)
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Frontend
cd frontend
pnpm dev        # runs on http://localhost:5174
```

### Why `uv run`?
The backend uses `uv` with a `.venv`. Running `uvicorn` directly picks up system Python which lacks the project dependencies. Always prefix with `uv run`.

### Infrastructure (docker-compose)
| Service | Image | Port |
|---|---|---|
| PostgreSQL + PostGIS | `postgis/postgis:16-3.4` | 5432 |
| Redis | `redis:7-alpine` | 6379 |
| Redis Commander | `rediscommander/redis-commander` | 8081 |

**DB credentials (dev):** `logistiq:dev_secret_123@localhost:5432/logistiq`

---

## 3. Backend Architecture

### Stack
- **Framework:** FastAPI (async) + Uvicorn
- **ORM:** SQLAlchemy 2.0 async (`AsyncSession`)
- **DB:** PostgreSQL 16 + PostGIS 3.4 (geospatial queries via GeoAlchemy2)
- **Cache/PubSub:** Redis (aioredis)
- **Auth:** JWT (HS256) via `python-jose`; bcrypt passwords
- **Logging:** `structlog` with stdlib bridge — ALL log lines include `service`, `env`, and request tracing IDs
- **Scheduling:** APScheduler `AsyncIOScheduler` (runs inside FastAPI lifespan)
- **Billing:** Stripe (partially mocked in dev)
- **AI:** Google Gemini (`google-generativeai`) — `gemini-1.5-flash` default
- **Deps managed by:** `uv` / `pyproject.toml`

### Module Map
```
backend/
├── main.py               # App factory, middleware, router registration, lifespan
├── core/
│   ├── config.py         # Pydantic-Settings (reads .env)
│   ├── auth.py           # JWT create/decode, get_current_user, require_role
│   ├── schemas.py        # Pydantic v2 request/response models
│   ├── exceptions.py     # Domain exceptions (NotFoundError, ForbiddenError, etc.)
│   ├── middleware.py     # TenantMiddleware (tracing, RLS injection)
│   ├── logging.py        # structlog configuration + context binding
│   └── redis.py          # redis_client singleton
├── db/
│   ├── models.py         # SQLAlchemy ORM models
│   ├── database.py       # AsyncSessionLocal, get_db_session dependency
│   ├── seed.py           # Dev seed script
│   └── migrations/       # Alembic
├── api/
│   ├── auth_routes.py
│   ├── shipment_routes.py
│   ├── disruption_routes.py
│   ├── analytics_routes.py
│   ├── billing_routes.py
│   └── websocket_routes.py
├── agents/
│   ├── sentinel_agent.py # Background scheduler: risk polling + GDELT scan
│   ├── decision_agent.py # Rerouting decisions (Gemini-powered)
│   ├── copilot_agent.py  # NL query interface
│   └── gdelt_scanner.py  # GDELT news → NewsAlert rows
├── mcp_servers/
│   ├── base.py           # MCPServer base class
│   ├── mcp_weather.py    # Flood/weather risk (Open-Meteo + Open-Elevation)
│   ├── mcp_satellite.py  # Fire/satellite data (NASA FIRMS)
│   ├── mcp_routing.py    # Multimodal route options (OSRM)
│   ├── mcp_shipment.py   # Shipment tool calls
│   └── mcp_notify.py     # Push notification tooling (Firebase)
├── ml/
│   └── risk_scorer.py    # compute_risk() — aggregates MCP signals → 0–1 score
└── billing/
    ├── stripe_client.py
    └── usage_tracker.py  # Redis-based API usage counters
```

### Middleware Stack (applied in reverse order)
1. **CORSMiddleware** — outermost, handles preflight
2. **TenantMiddleware** — generates `request_id`/`trace_id`, extracts `tenant_id` from JWT, sets `request.state.tenant_id` for RLS, adds `X-Request-ID`, `X-Trace-ID`, `X-Tenant-ID` headers

### Multi-Tenancy & RLS
- Every DB table has a `tenant_id UUID` FK → `tenants.id`
- PostgreSQL RLS is set via `SET LOCAL app.tenant_id` in `get_db_session`
- `TenantMiddleware` extracts `tenant_id` from JWT and puts it on `request.state`
- All route handlers call `_assert_tenant()` / `_check_tenant()` guards

### Auth Flow
- `POST /auth/register` → creates Tenant + Admin User → returns `{access_token, refresh_token}`
- `POST /auth/login` → rate-limited (5 attempts/min via Redis) → returns tokens
- `POST /auth/refresh` → exchanges refresh token for new pair
- `POST /auth/logout` → blacklists refresh token in Redis (`blacklist:{jti}`, TTL = 7 days)
- `GET /auth/me` → returns `UserProfile` with nested `TenantProfile`
- JWT: `access_token` expires in 15 min, `refresh_token` expires in 7 days

### Role Hierarchy
```
ADMIN > MANAGER > OPERATOR > VIEWER
```
Used via `require_role(UserRole.X)` FastAPI dependency.

---

## 4. REST API Reference

**Base URL (dev):** `http://localhost:8000`  
**All REST routes versioned under:** `/api/v1`  
Example: `GET http://localhost:8000/api/v1/analytics/summary`  
**All protected routes require:** `Authorization: Bearer <access_token>`

### Auth — prefix `/auth`
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | None | Register tenant + admin user |
| POST | `/auth/login` | None | Get tokens (rate-limited 5/min) |
| POST | `/auth/refresh` | None | Refresh access token |
| POST | `/auth/logout` | None | Blacklist refresh token |
| GET | `/auth/me` | Any | Get current user + tenant profile |

### Shipments — prefix `/shipments`
| Method | Path | Min Role | Description |
|---|---|---|---|
| GET | `/shipments` | VIEWER | List (filters: `status`, `mode`; pagination: `limit`, `offset`) |
| POST | `/shipments` | OPERATOR | Create shipment |
| GET | `/shipments/{id}` | VIEWER | Get single shipment |
| PATCH | `/shipments/{id}` | OPERATOR | Partial update (status, mode, dates) |
| DELETE | `/shipments/{id}` | MANAGER | Soft-delete (sets status=CANCELLED) |

### Carriers — prefix `/carriers`
| Method | Path | Min Role | Description |
|---|---|---|---|
| GET | `/carriers` | VIEWER | List carriers for tenant |
| POST | `/carriers` | MANAGER | Create carrier |
| GET | `/carriers/{id}` | VIEWER | Get single carrier |

### Disruptions — prefix `/disruptions`
| Method | Path | Min Role | Description |
|---|---|---|---|
| GET | `/disruptions` | VIEWER | List (filters: `type`, `severity`, `status`) |
| POST | `/disruptions` | MANAGER | Report disruption manually (requires `lat`, `lon`) |
| GET | `/disruptions/affected` | VIEWER | Shipments intersecting a disruption (PostGIS spatial query) |
| GET | `/disruptions/{id}` | VIEWER | Get single disruption |
| PATCH | `/disruptions/{id}/resolve` | MANAGER | Mark disruption resolved |

### Routes — prefix `/routes`
| Method | Path | Description |
|---|---|---|
| GET | `/routes/geojson` | GeoJSON FeatureCollection of all route segments for the tenant. Used by FreightMap PathLayer. Falls back to empty FeatureCollection if PostGIS unavailable. |

| Method | Path | Description |
|---|---|---|
| GET | `/analytics/summary` | KPI cards: totals, on-time %, active disruptions |
| GET | `/analytics/shipments/by-status` | Count grouped by ShipmentStatus |
| GET | `/analytics/shipments/by-mode` | Count grouped by ShipmentMode |
| GET | `/analytics/disruptions/trend` | Daily count for last N days (`?days=14`) |
| GET | `/analytics/risk/heatmap` | Top-N risky route segments from Redis (`?top_n=20`) |
| GET | `/analytics/usage` | Monthly API usage counters per tenant |

### Billing — prefix `/billing`
| Method | Path | Min Role | Description |
|---|---|---|---|
| GET | `/billing/status` | VIEWER | Current subscription info |
| POST | `/billing/subscribe` | ADMIN | Create Stripe subscription |
| POST | `/billing/cancel` | ADMIN | Cancel at period end |
| POST | `/billing/change-plan` | ADMIN | Upgrade/downgrade |
| GET | `/billing/portal` | ADMIN | Stripe Customer Portal URL |
| POST | `/billing/webhook` | None | Stripe webhook (no auth, signature-verified) |

### Ops
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe → `{status, service, env}` |
| GET | `/ready` | Readiness probe |
| GET | `/docs` | Swagger UI |

### MCP Tool Servers (internal HTTP)
Mounted at `/mcp/*` — called in-process by agents, not intended for frontend:
- `/mcp/weather` — `get_flood_risk`, `get_weather_forecast`
- `/mcp/satellite` — `get_fire_alerts` (NASA FIRMS)
- `/mcp/routing` — `get_multimodal_options` (OSRM)
- `/mcp/shipment` — shipment tool wrappers
- `/mcp/notify` — Firebase push notifications

---

## 5. WebSocket API

**Base URL (dev):** `ws://localhost:8000`  
**Auth:** JWT passed as `?token=<access_token>` query param (browser WS API limitation)  
**Note:** WS URLs do NOT use the `/api/v1` prefix.

| Path | Channel Key | Description |
|---|---|---|
| `/ws/shipments/all` | `shipments_all:{tenant_id}` | Fleet-wide live telemetry (all shipments for tenant) |
| `/ws/shipments/{shipment_id}` | `shipment:{tenant_id}:{shipment_id}` | Single shipment live telemetry |
| `/ws/disruptions` | `disruptions:{tenant_id}` | Tenant-wide disruption alerts |
| `/ws/dashboard` | `dashboard:{tenant_id}` | KPI stream (tick every 30s) |

**Message types sent by backend:**
- `init` — initial state on connect (shipment WS)
- `risk_alert` — `{type, shipment_id, risk_score, action, ts}`
- `new_disruption` — `{type, shipment_id, risk_score, disruption_type, ts}`
- `kpi_update` — `{type, total_shipments, in_transit, delayed, ts}`
- `gdelt_alerts` — `{type, count, ts}`
- `pong` — response to client `ping`
- `tick` — dashboard heartbeat every 30s

**Keepalive:** client sends `"ping"` text frame; backend replies `{type: "pong"}`. Backend timeout is 60s.

---

## 6. Background Agents

### SentinelAgent (`agents/sentinel_agent.py`)
Runs two APScheduler jobs inside FastAPI lifespan:

**Job 1: `check_all_shipments`** — every 5 min (configurable)
1. Fetches all `IN_TRANSIT` shipments across all tenants
2. Calls `compute_risk(lat, lon, segment_id, mcp_clients)` concurrently (max 10 parallel)
3. Risk ≥ 0.70 → marks `DELAYED`, creates `DisruptionEvent`, broadcasts WS alert
4. Risk ≥ 0.85 → additionally calls `decision_agent.decide_reroute()`
5. Persists `AgentDecision` rows for audit trail
6. Broadcasts KPI updates to `dashboard:{tenant_id}` channels

**Job 2: `run_gdelt_scan`** — every 10 min
- Scans GDELT news feed for logistics disruption keywords
- Creates `NewsAlert` rows
- Broadcasts to all tenant `disruptions:{tenant_id}` channels

**Geocoding stub:** City → (lat, lon) lookup for 14 Indian cities. Falls back to centre of India `(20.593, 78.963)`.

### CopilotAgent (`agents/copilot_agent.py`)
Natural-language query interface. Rate-limited at 20 calls/tenant/hour (Redis).

**Intent classification (regex-first, Gemini fallback):**
| Intent | Triggers |
|---|---|
| `shipment_status` | "where is shipment", "status", "delayed", "eta" |
| `risk_query` | "flood", "weather", "fire", "earthquake" |
| `route_suggestion` | "route", "reroute", "best path", "multimodal" |
| `analytics` | "how many", "count", "report", "this week" |
| `general` | Anything else → Gemini `gemini-1.5-flash` |

**Returns:** `CopilotResponse {answer, intent, tool_calls, confidence, sources, fallback_used}`

### DecisionAgent (`agents/decision_agent.py`)
Called by SentinelAgent for critical-risk shipments. Uses Gemini to recommend rerouting options, persists `AgentDecision`.

### GDELTScanner (`agents/gdelt_scanner.py`)
Polls GDELT RSS feed for India logistics keywords. Creates `NewsAlert` rows per tenant.

---

## 7. Database Models

All models use `gen_random_uuid()` as primary key (UUID string). All have `created_at` / `updated_at` timestamps.

### Enums
```python
ShipmentStatus: pending | in_transit | delivered | delayed | cancelled
ShipmentMode:   road | rail | air | sea
DisruptionType: weather | traffic | accident | strike | natural_disaster | security
DisruptionSeverity: low | medium | high | critical
UserRole:       admin | manager | operator | viewer
PlanTier:       starter | pro | enterprise
```

### Tables
| Table | Key Fields |
|---|---|
| `tenants` | `id`, `name` |
| `users` | `id`, `tenant_id`, `email`, `role`, `hashed_password` |
| `carriers` | `id`, `tenant_id`, `name` |
| `shipments` | `id`, `tenant_id`, `carrier_id`, `status`, `mode`, `origin`, `destination`, `sector`, `weight_kg`, `volume_m3`, `temperature_c`, `estimated_delivery`, `actual_delivery` |
| `route_segments` | `id`, `shipment_id`, `geom (LINESTRING SRID=4326)`, `sequence`, `distance_km`, `estimated_duration_h` |
| `disruption_events` | `id`, `tenant_id`, `type`, `severity`, `status`, `center_geom (POINT SRID=4326)`, `radius_km`, `description`, `impact` |
| `agent_decisions` | `id`, `tenant_id`, `shipment_id`, `decision (JSON)`, `confidence`, `action_taken` |
| `telemetry` | `id`, `shipment_id`, `ts`, `data (JSON)` |
| `news_alerts` | `id`, `tenant_id`, `title`, `content`, `category`, `priority` |
| `subscription_events` | `id`, `tenant_id`, `user_id`, `event_type`, `details (JSON)` |

**PostGIS:** `route_segments.geom` and `disruption_events.center_geom` are spatial columns. Spatial queries use `ST_DWithin` with geography cast for disruption-affected shipments.

**⚠️ Schema change:** `DisruptionRead` now includes optional `lat: float | None` and `lon: float | None` fields. These are populated when the handler extracts coordinates from `center_geom` (PostGIS). Frontend FreightMap can now synthesise GeoJSON from disruption list responses.

**⚠️ ORM fix:** `Tenant` model now has `disruption_events` and `agent_decisions` back-reference relationships that were previously missing, which caused SQLAlchemy mapper configuration errors.

---

## 8. Frontend Architecture

### Stack
- **Framework:** React 18 + Vite + TypeScript (strict)
- **Routing:** React Router v6 (`createBrowserRouter`)
- **State:** Zustand (5 stores)
- **Data fetching:** TanStack Query v5 (30s staleTime, retry 2)
- **HTTP client:** Axios (`apiClient`) with JWT interceptor
- **Map:** `react-map-gl/maplibre` + `deck.gl` (`@deck.gl/mapbox` MapboxOverlay)
- **Map tiles:** Stadia Maps "Alidade Smooth Dark" (free for localhost)
- **Styling:** Vanilla CSS (`index.css`) + `App.css` — custom `lq-*` class prefix
- **Package manager:** `pnpm`
- **Path alias:** `@/` → `src/`

### Route Structure
```
/login                  ← public, LoginPage
/ (redirect → /dashboard)
/dashboard              ← AuthGuard + AppShell
/tracking               ← FreightMap (full geospatial view)
/risk
/routes
/analytics
/reports
/copilot
/billing
/settings
* → /dashboard (catch-all)
```
All routes except `/login` are wrapped in `AuthGuard` → `AppShell`.

### Component Structure
```
src/
├── App.tsx                        # Router + QueryClientProvider
├── components/
│   ├── auth/AuthGuard.tsx          # Redirects to /login if no token
│   ├── layout/AppShell.tsx         # Sidebar + TopBar + <Outlet />
│   ├── map/
│   │   ├── FreightMap.tsx          # Main map component
│   │   └── layerConfigs.ts         # deck.gl layer factories
│   └── ui/                         # Shared UI primitives
├── pages/                          # Lazy-loaded route pages
├── stores/
│   ├── auth.store.ts               # token, user, tenant → sessionStorage
│   ├── map.store.ts                # layers toggle state {flood,fire,cargo,heatmap}
│   ├── shipment.store.ts           # selectedShipment for side panel
│   ├── sidebar.store.ts            # collapsed state
│   └── alert.store.ts              # global alerts list
├── hooks/
│   └── useWebSocket.ts             # Reconnecting WS with exponential back-off
├── lib/
│   ├── api.ts                      # Axios instance + QueryClient
│   └── utils.ts
└── types/
    ├── auth.types.ts
    ├── freight.types.ts            # WsShipmentFrame, DisruptionFeature, etc.
    ├── shipment.types.ts
    ├── map.types.ts
    ├── alert.types.ts
    └── api.types.ts
```

### Zustand Stores
| Store | Persisted | Key State |
|---|---|---|
| `useAuthStore` | sessionStorage (`lq-auth`) | `token`, `user`, `tenant` |
| `useMapStore` | No | `layers: {flood, fire, cargo, heatmap}` |
| `useShipmentStore` | No | `selectedShipment` |
| `useSidebarStore` | No | `collapsed` |
| `useAlertStore` | No | `alerts[]` |

### API Client (`src/lib/api.ts`)
```typescript
// Axios instance
apiClient.baseURL = VITE_API_URL ?? 'http://localhost:8000/api/v1'
// Request interceptor: injects Authorization + X-Tenant-ID headers
// Response interceptor: 401 → logout() + redirect to /login
```

### FreightMap (`src/components/map/FreightMap.tsx`)
Key architecture decisions:
- `Map` component imported as `Map as MapGL` to avoid shadowing native JS `Map` constructor
- `shipmentsRef`: native JS `Map<string, WsShipmentFrame>` for O(1) updates
- `useWebSocket('/ws/shipments/all')` → live fleet telemetry
- deck.gl layers: `HeatmapLayer` → `ScatterplotLayer` (hazards) → `PathLayer` (routes) → `ArcLayer` → `ScatterplotLayer` (shipments)
- Layer visibility driven by `useMapStore.layers`
- Shipment click → `useShipmentStore.setSelected` → opens side panel

### `useWebSocket` Hook
- Exponential back-off reconnection: 1s → 2s → 4s → ... → 30s cap
- Sends `"ping"` every 30s, ignores non-JSON frames silently
- JWT injected as `?token=` query param
- Stable refs pattern — no stale closures

---

## 9. Frontend Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000/api/v1` | Axios baseURL |
| `VITE_WS_URL` | `ws://localhost:8000` | WebSocket base |
| `VITE_STADIA_MAPS_STYLE` | Alidade Smooth Dark JSON URL | Map tile style |
| `VITE_STADIA_MAPS_API_KEY` | (none — optional for localhost) | Stadia Maps key for prod |

---

## 10. Backend Environment Variables (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://logistiq:dev_secret_123@localhost:5432/logistiq` | |
| `REDIS_URL` | `redis://localhost:6379` | |
| `SECRET_KEY` | `your_secret_key` | **Change in prod** |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `ALLOWED_ORIGINS` | `["http://localhost"]` | CORS list |
| `GEMINI_API_KEY` | None | Google AI key; Copilot falls back to templates without it |
| `GEMINI_MODEL` | `gemini-1.5-flash` | |
| `NASA_FIRMS_KEY` | None | Satellite fire data |
| `ORS_API_KEY` | None | OpenRouteService (routing) |
| `FIREBASE_CREDENTIALS_JSON` | None | Push notifications |
| `STRIPE_SECRET_KEY` | None | Billing (mocked without it) |
| `RISK_THRESHOLD_DELAY` | `0.70` | Risk score above which shipment is marked DELAYED |
| `RISK_THRESHOLD_CRITICAL` | `0.85` | Risk score above which reroute is triggered |
| `SENTINEL_POLL_INTERVAL_MINUTES` | `5` | |
| `GDELT_POLL_INTERVAL_MINUTES` | `10` | |
| `ENVIRONMENT` | `development` | Warns if insecure defaults used in prod |

---

## 11. Code Style & Conventions

### Backend (Python)
- Python 3.11+, `from __future__ import annotations` on every file
- Pydantic v2 (`model_dump`, `model_config`, `model_validator`)
- `structlog.get_logger(__name__)` — never use `print()` or `logging.basicConfig()`
- Log event names use dot notation: `"shipment.created"`, `"sentinel.poll_start"`
- Domain exceptions from `core/exceptions.py` — never raise bare `HTTPException` from business logic (only from route handlers if needed)
- Route files have a module docstring listing all endpoints
- Helper functions prefixed with `_` for private; `_assert_tenant()` pattern for ownership checks
- `async with AsyncSessionLocal() as db:` for DB access outside of request context (agents)
- Ruff linting: line length 100, target Python 3.11

### Frontend (TypeScript)
- Strict TypeScript — no `any` without explicit `// type: ignore` comment
- CSS class prefix: `lq-` for all custom classes
- Zustand stores: one file per store, `use*Store` naming
- TanStack Query keys: `['resource', 'qualifier']` array pattern
- Components: named exports (not default) except pages
- `useCallback` + `useMemo` for all handlers passed to deck.gl layers
- `useRef` for values that shouldn't trigger re-renders (WS refs, shipment cache)
- Import `Map as MapGL` from `react-map-gl/maplibre` — **never** import bare `Map` (shadows native JS `Map`)

---

## 12. Known Issues & TODOs

| Area | Issue | Status |
|---|---|---|
| `/ws/shipments/all` | ✅ Added fleet-wide WS broadcast channel | ✅ DONE |
| `/routes/geojson` | ✅ Endpoint implemented; falls back gracefully when no route segments exist | ✅ DONE |
| `DisruptionRead` schema | ✅ `lat`/`lon` fields added; extracted from PostGIS `center_geom` in route handlers | ✅ DONE |
| API versioning | ✅ All REST routes now under `/api/v1` prefix matching frontend `VITE_API_URL` | ✅ DONE |
| CORS | ✅ `localhost:5174` (Vite dev server) added to `ALLOWED_ORIGINS` | ✅ DONE |
| Geocoding | City → lat/lon is a hardcoded stub (14 cities) — needs real geocoder | ⏳ TODO |
| Copilot page | `CopilotPage.tsx` is a stub placeholder | ⏳ TODO |
| Dashboard page | ✅ Implemented via `DashboardView` | ✅ DONE |
| Most pages | `AnalyticsPage`, `RiskPage`, `RoutesPage` etc. are stubs | ⏳ TODO |
| Automated Tests | ⚠️ Suite fails due to `aiosqlite` lacking PostGIS support for spatial types. Use **Manual Testing Guide** (Section 8) until Dockerised PostGIS tests are set up. | ⏳ TODO |
| TypeScript types | ✅ `DisruptionEntry.type`, `DisruptionType`, `User.role`, `Tenant.plan` expanded to match backend enums | ✅ DONE |
| `WsShipmentMessage` | ✅ Added `connected` and `tick` message types to discriminated union | ✅ DONE |

---

## 8. End-to-End Manual Testing Guide

Since the automated SQLite test suite currently lacks PostGIS support, use the following manual testing procedures against a running `docker-compose` or local dev environment to verify production readiness.

### Prerequisites
- Start backend: `cd backend && uv run uvicorn main:app --reload`
- Start frontend: `cd frontend && npm run dev`
- Ensure Redis and PostGIS are running (`docker-compose up -d redis db` if applicable).

### Phase 1: Authentication & App Shell
1. Navigate to `http://localhost:5174/login` (or the port Vite is using).
2. Enter a mock email (`operator@logistiq.ai`) and any password. The backend mock login currently accepts any valid credentials if rate limits aren't exceeded.
3. Verify successful redirection to `/dashboard`.
4. Check the `sessionStorage` in DevTools to ensure `lq-auth` contains a valid `token`, `user`, and `tenant`.
5. Verify the Sidebar displays your `user.role` (e.g., Operator) and the header shows the Tenant name.

### Phase 2: Dashboard Real-Time Telemetry
1. On the `/dashboard` page, observe the **KPI Strip** at the top. Wait for 30 seconds.
2. The `/ws/dashboard` WebSocket should emit a `tick` message every 30 seconds, and the KPI numbers should refresh. You can verify this in the Network Tab -> WS.
3. Observe the **Agent Logs** and **Disruption Feed** on the right side of the screen.

### Phase 3: Geospatial Layers (FreightMap)
1. The central map (`deck.gl`) should render three primary layers:
   - **Shipment ScatterplotLayer**: Small dots representing active shipments (yellow/amber for at-risk, blue for active).
   - **Route PathLayer**: Lines showing the paths.
   - **Hazard GeoJsonLayer**: Transparent red/amber/blue circles showing active disruptions.
2. If the map is empty, create a mock shipment and route via the backend API:
   ```bash
   # Create a disruption (requires valid auth token in header)
   curl -X POST "http://localhost:8000/api/v1/disruptions" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"type":"weather","severity":"high","description":"Severe Storm","lat":19.0760,"lon":72.8777,"radius_km":50.0}'
   ```
3. After creating the disruption, verify that the **Disruption Feed** updates immediately via WebSocket (`/ws/disruptions`).
4. Verify the FreightMap renders the newly created disruption as a hazard circle.

### Phase 4: Fleet-Wide Tracking
1. The FreightMap connects to `/ws/shipments/all`. Ensure the connection succeeds (Network Tab).
2. If the `sentinel_agent` is running in the background, it will periodically push telemetry updates to this channel.
3. Verify that shipments on the map update their colors or positions based on the WS telemetry payloads.

> [!NOTE]
> If you experience silent WebSocket failures, ensure the `VITE_WS_URL` in your frontend `.env` matches the backend host (e.g., `ws://localhost:8000`) and the JWT token has not expired.

---

## 16. DashboardView

**File:** `src/views/DashboardView.tsx` — rendered by `src/pages/DashboardPage.tsx`

### Layout
```
┌─────────────────────────────────────────────────────────┐
│  KPI Strip  (5 cards, polling /analytics/summary, 30s)  │
├──────────────────────────────────┬──────────────────────┤
│  FreightMap  (65%)               │  Right Panel  (35%)  │
│  + WS live badge                 │  [Disruptions][Log]  │
└──────────────────────────────────┴──────────────────────┘
```

### KPI Cards (5)
| Card | Backend field | Accent |
|---|---|---|
| Active Shipments | `summary.in_transit` | cyan |
| At Risk | `summary.delayed` | amber (pulsing dot) |
| Active Disruptions | `summary.active_disruptions` | red |
| SLA Compliance % | `summary.on_time_rate_pct` | green (+ progress bar) |
| CO₂ Saved Today | `in_transit × 0.12` (mock) | violet |

### WebSocket Subscriptions
| Channel | Messages handled |
|---|---|
| `/ws/disruptions` | `new_disruption` → `pushDisruption()`, `gdelt_alerts` → `pushAgentLog()` |
| `/ws/dashboard` | `risk_alert` → `pushAgentLog()`, `kpi_update` → (future: invalidate query) |

### Right Panel Tabs
- **Disruptions** — merges REST seed (`GET /disruptions`) + live WS push. Each row: colored left border, hazard emoji, summary, region, severity badge, mini risk bar, affected count. Click → `DisruptionSheet` overlay.
- **Agent Log** — terminal-style monospace list from `useAlertStore.agentLog`. Max 50 entries rendered, max 200 stored. New entries animate in via `lq-log-slide` keyframe (translateY -8px → 0, 200ms).

### DisruptionSheet
Inline side-sheet (no external deps) with slide-in animation (`lq-sheet-in`). Closes on `X` button, backdrop click, or `Escape` key.

### CSS Classes Added
All prefixed `lq-dash-*` or `lq-kpi-*` etc. in `index.css`. New utility: `.lq-content--flush` applied by `AppShell` on `/dashboard` and `/tracking` routes to remove padding/overflow for full-height layouts.

### AppShell Change
`AppShell.tsx` now uses `useLocation()` to detect flush routes. When `pathname === '/dashboard' || '/tracking'`, applies `.lq-content--flush` to `<main>`.


---

## 13. Pydantic Schemas Quick Reference

### Request Bodies
```python
RegisterRequest:    email, password, company_name, first_name, last_name
UserLogin:          email, password
ShipmentCreate:     origin, destination, sector, mode, carrier_id?, weight_kg?, volume_m3?, temperature_c?, estimated_delivery?
ShipmentUpdate:     status?, mode?, carrier_id?, weight_kg?, volume_m3?, temperature_c?, estimated_delivery?, actual_delivery?
CarrierCreate:      name (1–255 chars)
DisruptionCreate:   type, severity, lat, lon, radius_km?, description?, impact?
SubscribeRequest:   plan_tier (starter|pro|enterprise), trial_days (0–30)
ChangePlanRequest:  plan_tier
```

### Response Models
```python
Token:              access_token, refresh_token, token_type
UserProfile:        id, email, full_name, role, tenant_id, created_at, tenant: TenantProfile
ShipmentRead:       id, tenant_id, carrier_id, status, mode, origin, destination, sector, weight_kg, volume_m3, temperature_c, estimated_delivery, actual_delivery, created_at, updated_at
DisruptionRead:     id, tenant_id, type, severity, status, radius_km, description, impact, created_at, updated_at
PaginatedResponse:  total, offset, limit, items[]
BillingStatusRead:  plan_tier, status, stripe_customer_id, details{}
```

---

## 14. WebSocket Message Types (Frontend Types)

```typescript
// freight.types.ts
WsShipmentFrame: {
  type: 'update'; shipment_id: string; tracking_number: string;
  lat: number; lng: number; origin: string; destination: string;
  status: string; mode: string; sector: string;
  risk_score: number; eta: string | null; ts: string;
}
WsShipmentMessage: WsShipmentFrame | { type: 'init' | 'pong' | 'tick' | ... }
DisruptionFeatureCollection: GeoJSON FeatureCollection
DisruptionFeature: GeoJSON Feature<Point, DisruptionFeatureProperties>
RouteSegmentCollection: GeoJSON FeatureCollection<LineString>
```

---

## 15. MCP Tool Reference

MCP servers expose an `execute_tool(tool_name, params, tenant_id)` async method. Called in-process by agents via `InProcessMCPClient`.

| Server | Tools |
|---|---|
| `mcp_weather` | `get_flood_risk(lat, lon)`, `get_weather_forecast(lat, lon)` |
| `mcp_satellite` | `get_fire_alerts(lat, lon, radius_km)` |
| `mcp_routing` | `get_multimodal_options(origin, destination, weight_kg)` |
| `mcp_shipment` | Shipment DB queries as tool calls |
| `mcp_notify` | `send_push_notification(tenant_id, title, body)` |

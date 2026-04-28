# LogistiQ AI — Architecture & Developer Context

> **AI Pair-Programming Context** — This document is the authoritative reference for any AI assistant, new engineer, or automated tool working on this codebase. Read it before making changes.

---

## Project Overview

LogistiQ AI is a **multi-tenant, AI-powered logistics disruption management platform** designed for the Indian supply-chain market. It combines real-time geospatial risk assessment, autonomous rerouting agents, and metered SaaS billing.

**Stack snapshot:**

| Layer | Technology |
|---|---|
| API | FastAPI 0.136+ (async, Python 3.11) |
| Database | PostgreSQL 16 + PostGIS 3.4 (RLS-isolated per tenant) |
| Cache / PubSub | Redis 7 |
| ORM | SQLAlchemy 2.0 async + Alembic |
| AI agents | Google Gemini 1.5 Flash (ReAct loop via `google-generativeai`) |
| ML | OR-Tools (CVRP / VRP solver) |
| Background jobs | APScheduler (AsyncIOScheduler) |
| NLP | spaCy + keyword classifier (GDELT news scanner) |
| Billing | Stripe (subscriptions + metered usage) |
| Notifications | Firebase Cloud Messaging |
| Infra | GCP Cloud Run (API) + Firebase Hosting (frontend) |
| CI/CD | GitHub Actions + GCP Cloud Build |

---

## Directory Structure

```
logistiq-ai/
├── backend/
│   ├── main.py                    # FastAPI app, lifespan, middleware, exception handlers
│   ├── alembic.ini                # Alembic CLI config (DATABASE_URL overridden by env.py)
│   ├── core/
│   │   ├── auth.py                # JWT (jose), bcrypt, HTTPBearer dep, require_role()
│   │   ├── config.py              # Pydantic Settings — single source of truth for env vars
│   │   ├── exceptions.py          # LogistiQError hierarchy → JSON responses
│   │   ├── logging.py             # structlog + stdlib bridge, trace_id context var
│   │   ├── middleware.py          # TenantMiddleware: sets app.tenant_id, request tracing
│   │   ├── redis.py               # redis_client singleton
│   │   └── schemas.py             # Pydantic v2 request/response models
│   ├── db/
│   │   ├── database.py            # Async engine, AsyncSessionLocal, get_db_session dep
│   │   ├── models.py              # All SQLAlchemy 2.0 ORM models
│   │   ├── seed.py                # Dev seed script (creates tenants, users, shipments)
│   │   └── migrations/
│   │       ├── env.py             # Alembic async env (reads settings.DATABASE_URL)
│   │       ├── script.py.mako     # Template for new revision files
│   │       └── versions/
│   │           └── 001_initial_schema.py
│   ├── api/
│   │   ├── auth_routes.py         # /auth/register, /login, /me, /refresh, /logout
│   │   ├── shipment_routes.py     # /shipments CRUD + /carriers CRUD
│   │   ├── disruption_routes.py   # /disruptions CRUD + /resolve + /affected (PostGIS)
│   │   ├── analytics_routes.py    # /analytics/summary, /by-status, /by-mode, /usage, /risk/heatmap
│   │   ├── billing_routes.py      # /billing/status, /subscribe, /cancel, /portal, /webhook
│   │   └── websocket_routes.py    # WS /ws/shipments/{id}, /ws/disruptions, /ws/dashboard
│   ├── agents/
│   │   ├── sentinel_agent.py      # APScheduler: polls IN_TRANSIT shipments every 5 min
│   │   ├── decision_agent.py      # Gemini ReAct loop: reroutes CRITICAL shipments
│   │   ├── copilot_agent.py       # NL query interface for operators
│   │   └── gdelt_scanner.py       # GDELT RSS + keyword NLP → DisruptionEvent rows
│   ├── mcp_servers/
│   │   ├── base.py                # MCPServer abstract class + MCPClient Protocol
│   │   ├── mcp_weather.py         # Open-Meteo + flood risk scoring
│   │   ├── mcp_satellite.py       # NASA FIRMS (fire) + USGS earthquake data
│   │   ├── mcp_routing.py         # OpenRouteService routes + VRP alternates
│   │   ├── mcp_shipment.py        # Shipment read/update tools
│   │   └── mcp_notify.py          # Firebase FCM push notifications
│   ├── ml/
│   │   ├── risk_scorer.py         # Composite risk formula (flood+fire+strike+quake)
│   │   └── vrp_solver.py          # OR-Tools CVRP wrapper + find_alternates()
│   ├── billing/
│   │   ├── stripe_client.py       # Async Stripe SDK wrapper (fail-safe in dev)
│   │   └── usage_tracker.py       # Redis-backed metered billing counters
│   └── tests/
│       ├── conftest.py            # SQLite in-memory DB, fakeredis, mock MCP clients
│       ├── unit/                  # Pure logic tests (no HTTP)
│       └── integration/           # Full route tests via httpx.AsyncClient + TestClient
├── frontend/                      # React SPA (Vite)
├── infra/
│   ├── Dockerfile.backend         # Multi-stage Python 3.11 production image
│   ├── Dockerfile.frontend        # Node 20 build → nginx:alpine serve
│   ├── docker-compose.yml         # Full local dev stack
│   └── cloudbuild.yaml            # GCP Cloud Build pipeline
├── .github/
│   └── workflows/ci.yml           # GitHub Actions: quality + deploy + weekly-benchmark
└── docs/
    ├── AI_CONTEXT.md              # ← You are here
    └── swagger.json               # OpenAPI 3.1 export (auto-generated by CI)
```

---

## Core Architectural Patterns

### 1. Multi-Tenant Row-Level Security (RLS)

Every tenant-scoped table has a PostgreSQL RLS policy:
```sql
CREATE POLICY tenant_isolation ON "shipments"
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

`TenantMiddleware` (in `core/middleware.py`) extracts `tenant_id` from the JWT and sets it on `request.state`. `get_db_session` (in `db/database.py`) then runs:
```sql
SET LOCAL app.tenant_id = '<uuid>';
```
before yielding the session, activating RLS for that request.

> **⚠️ Never bypass RLS** by querying without `tenant_id` context outside of the sentinel agent (which intentionally queries all tenants via `AsyncSessionLocal` without the RLS session var).

### 2. Exception Hierarchy

All domain errors inherit from `LogistiQError` in `core/exceptions.py`. The global exception handler in `main.py` catches any `LogistiQError` and converts it to a structured JSON response:
```json
{ "error": "not_found", "message": "Shipment abc-123 not found" }
```

**Never** `raise HTTPException` directly in route handlers — always raise the appropriate `LogistiQError` subclass.

### 3. MCP Tool Server Pattern

Each external data source is wrapped as an `MCPServer` subclass:
```
MCPServer (base.py)
  ├── WeatherMCPServer   → Open-Meteo
  ├── SatelliteMCPServer → NASA FIRMS + USGS
  ├── RoutingMCPServer   → OpenRouteService
  ├── ShipmentMCPServer  → internal DB reads
  └── NotifyMCPServer    → Firebase FCM
```

MCP servers expose `execute_tool(tool_name, params, tenant_id)` and are mounted as HTTP routers (`/mcp/*`). The sentinel and decision agents call them **in-process** via `InProcessMCPClient` to avoid HTTP overhead.

### 4. Agent Pipeline

```
APScheduler (every 5 min)
  └─► sentinel_agent._check_all_shipments()
        └─► compute_risk(lat, lon, segment_id, mcp_clients)   [ml/risk_scorer.py]
              ├─► weather MCP (flood risk score)
              ├─► satellite MCP (fire proximity, quake score)
              └─► redis (strike probability from GDELT scan)
        ├─► risk ≥ 0.70 → mark DELAYED + create DisruptionEvent
        ├─► risk ≥ 0.85 → decide_reroute()                    [agents/decision_agent.py]
        │     └─► Gemini ReAct loop (up to 5 turns)
        │           ├─► get_route / get_alternatives / get_forecast_72h
        │           └─► DECISION → AgentDecision row
        └─► WebSocket broadcast (shipment + disruption channels)

APScheduler (every 10 min)
  └─► gdelt_scanner.scan_gdelt_news()
        └─► GDELT RSS → classify_article() → strike_probability in Redis
```

### 5. WebSocket Real-Time Updates

Three channel types, all in `api/websocket_routes.py`:

| Channel key | Producer | Consumer |
|---|---|---|
| `shipment:{tenant_id}:{shipment_id}` | `sentinel_agent` | Per-shipment tracking UI |
| `disruptions:{tenant_id}` | `sentinel_agent` + `gdelt_scanner` | Disruption alert panel |
| `dashboard:{tenant_id}` | `sentinel_agent._broadcast_dashboard_kpis()` | KPI dashboard cards |

Auth: JWT passed as `?token=<access_token>` query param (browser WS API limitation).

---

## Development Setup

```bash
# 1. Clone and enter backend
cd logistiq-ai/backend

# 2. Install uv (if not already installed)
pip install uv

# 3. Install all deps including dev group
uv sync --all-groups

# 4. Copy and edit env
cp .env.example .env
# → At minimum set GEMINI_API_KEY for agent testing

# 5. Run full local stack (Postgres + Redis + hot-reload API)
docker compose -f infra/docker-compose.yml up --build

# 6. Apply DB migrations
cd backend && alembic upgrade head

# 7. Seed dev data
uv run python db/seed.py

# 8. Run tests
uv run pytest -v
```

---

## Running Migrations

```bash
# Apply all pending migrations
cd backend
alembic upgrade head

# Generate a new migration after changing models.py
alembic revision --autogenerate -m "add_field_foo_to_shipments"

# Roll back one revision
alembic downgrade -1

# Show current revision
alembic current

# Show full migration history
alembic history --verbose
```

> **Note:** Alembic autogenerate does **not** detect PostGIS-specific things like RLS policies or GiST indexes. Always review auto-generated migrations before applying.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://...` | Async PostgreSQL connection string |
| `REDIS_URL` | ✅ | `redis://localhost:6379` | Redis connection |
| `SECRET_KEY` | ✅ | `your_secret_key` | JWT signing key (min 32 chars in prod) |
| `GEMINI_API_KEY` | For agents | `None` | Google Gemini API key |
| `STRIPE_SECRET_KEY` | For billing | `None` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | For billing | `None` | Stripe webhook signing secret |
| `STRIPE_STARTER_PRICE_ID` | For billing | `None` | Stripe price ID for starter plan |
| `STRIPE_PRO_PRICE_ID` | For billing | `None` | Stripe price ID for pro plan |
| `STRIPE_ENTERPRISE_PRICE_ID` | For billing | `None` | Stripe price ID for enterprise plan |
| `NASA_FIRMS_KEY` | For satellite MCP | `None` | NASA FIRMS API key |
| `ORS_API_KEY` | For routing MCP | `None` | OpenRouteService API key |
| `FIREBASE_CREDENTIALS_JSON` | For notify MCP | `None` | Firebase service account JSON (stringified) |
| `RISK_THRESHOLD_DELAY` | No | `0.70` | Risk score to mark shipment DELAYED |
| `RISK_THRESHOLD_CRITICAL` | No | `0.85` | Risk score to trigger emergency reroute |
| `SENTINEL_POLL_INTERVAL_MINUTES` | No | `5` | How often sentinel polls all shipments |
| `ENVIRONMENT` | No | `development` | `development` / `test` / `production` |

---

## Test Architecture

```
tests/
├── conftest.py          Shared fixtures:
│                         - db_session: SQLite in-memory (StaticPool, recreated per test)
│                         - redis_mock: fakeredis.aioredis.FakeRedis
│                         - mock_weather_client, mock_satellite_client, mock_mcp_clients
│                         - sample_tenant, sample_user, sample_operator, sample_shipment
│                         - admin_token, operator_token
│                         - app_client: httpx.AsyncClient(ASGITransport)
├── unit/
│   ├── test_auth.py           JWT create/decode, bcrypt hashing
│   ├── test_exceptions.py     Exception hierarchy, status codes, to_dict() contracts
│   ├── test_risk_scorer.py    Haversine, fire proximity, quake score, compute_risk()
│   ├── test_gdelt_scanner.py  classify_article(), _article_segment_id()
│   └── test_usage_tracker.py  record_event(), get_monthly_usage(), check_limit()
└── integration/
    ├── test_auth_routes.py        register, login, /me, logout
    ├── test_shipment_routes.py    CRUD shipments + carriers
    ├── test_analytics_routes.py   summary, by-status, by-mode, usage, heatmap
    ├── test_billing_routes.py     status, subscribe (dev mode), webhook, cancel, portal
    ├── test_disruption_routes.py  list/filter, create, get, resolve, affected, isolation
    └── test_websocket_routes.py   WS connect, ping/pong, auth rejection, ConnectionManager
```

**Key test constraints:**
- SQLite has **no PostGIS** — disruption tests insert raw WKT strings and spatial queries return `[]` gracefully
- WS tests use `starlette.testclient.TestClient.websocket_connect()` (synchronous), not httpx
- All external APIs (Gemini, Stripe, NASA FIRMS) are mocked — no live credentials needed

---

## Risk Score Formula

```
risk_score = (
    W_FLOOD  * weather_risk     +   # 0.40
    W_FIRE   * fire_proximity   +   # 0.25
    W_QUAKE  * quake_score      +   # 0.20
    W_STRIKE * strike_score         # 0.15
)
```

Where:
- `weather_risk` ← Open-Meteo rain + elevation data (0–1)
- `fire_proximity` ← NASA FIRMS: 0.9 if fire within 5km, 0.6 within 10km, else 0
- `quake_score` ← USGS: `min(magnitude/5, 1) × (1 - depth_km/30)`, only magnitudes ≥ 3.5
- `strike_score` ← GDELT RSS keyword classifier score, cached in Redis as `news:{segment_id}:strike_probability`

---

## Known Limitations / TODOs

- `_geocode_city()` in `sentinel_agent.py` uses a hardcoded dict of Indian city coords — replace with a real geocoder (e.g. Google Maps Geocoding API) for production
- `DisruptionEvent.center_geom` is stored as a plain WKT string in SQLite tests; PostGIS validates geometry types in production — ensure test fixtures stay in sync with schema changes
- `copilot_agent.py` NL query interface — currently parses free-form queries but doesn't yet stream responses; add Server-Sent Events (SSE) or WS streaming
- `mcp_satellite.py` NASA FIRMS key is optional — in dev/test, it falls back to empty feature lists
- Alembic autogenerate does not handle PostGIS-specific index types (GiST) — review all auto-generated migrations manually

---

## API Reference

The live OpenAPI spec is served at `/docs` (Swagger UI) and `/openapi.json` (raw JSON) when the server is running.

A static export is maintained at `docs/swagger.json` and regenerated by CI on every main branch deploy.

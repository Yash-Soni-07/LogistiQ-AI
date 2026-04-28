"""
main.py — FastAPI application entry point for LogistiQ AI.

Responsibilities:
  - App instantiation with lifespan context manager
  - Middleware registration (TenantMiddleware, CORS)
  - Prometheus instrumentation
  - Global exception handlers
  - Router mounting (API + MCP)
  - /health liveness endpoint
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from core.config import settings
from core.exceptions import LogistiQError
from core.logging import configure_logging
from core.middleware import TenantMiddleware
from db.database import AsyncSessionLocal, engine

log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── STARTUP ──────────────────────────────────────────────
    configure_logging()
    log.info("logistiq.startup", env=settings.ENVIRONMENT, version="1.0.0")

    # Verify DB + Redis connectivity.
    # Skipped when settings.TESTING=True to avoid asyncio event-loop
    # contamination across function-scoped pytest fixtures.
    if not settings.TESTING:
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            log.info("db.connected")
        except Exception as exc:  # noqa: BLE001
            log.error("db.connection_failed", error=str(exc))

        try:
            from core.redis import redis_client
            await redis_client.ping()
            log.info("redis.connected")
        except Exception as exc:  # noqa: BLE001
            log.error("redis.connection_failed", error=str(exc))


    # Start Sentinel Agent scheduler (disabled in test/CI environments and Phase 1).
    sentinel = None
    if not settings.TESTING and settings.PHASE_2_ENABLED:
        try:
            from agents.sentinel_agent import SentinelAgent
            sentinel = SentinelAgent()
            await sentinel.start()
        except Exception as exc:  # noqa: BLE001
            log.error("sentinel.start_failed", error=str(exc))

        try:
            import asyncio
            from agents.decision_agent import DecisionAgent
            decision_agent = DecisionAgent()
            task = asyncio.create_task(decision_agent.subscribe_disruptions())
            app.state.decision_agent_task = task
            app.state.decision_agent = decision_agent
            log.info("decision_agent.subscriber.started")
        except Exception as exc:  # noqa: BLE001
            log.error("decision_agent.start_failed", error=str(exc))

    yield

    # ── SHUTDOWN ─────────────────────────────────────────────
    if sentinel is not None:
        try:
            await sentinel.stop()
        except Exception:  # noqa: BLE001
            pass
    
    if getattr(app.state, "decision_agent_task", None):
        app.state.decision_agent_task.cancel()
        log.info("decision_agent.subscriber.stopped")

    if not settings.TESTING:
        try:
            await engine.dispose()
            log.info("db.disposed")
        except Exception:  # noqa: BLE001
            pass

        try:
            from core.redis import redis_client
            await redis_client.aclose()
            log.info("redis.closed")
        except Exception:  # noqa: BLE001
            pass

    log.info("logistiq.shutdown")



# ─────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="LogistiQ AI",
    version="1.0.0",
    description="AI-powered predictive supply chain & disruption management platform",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
)


# ─────────────────────────────────────────────────────────────
# Middleware  (order: first added = outermost layer)
# ─────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TenantMiddleware)


# ─────────────────────────────────────────────────────────────
# Prometheus
# ─────────────────────────────────────────────────────────────

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=False,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


# ─────────────────────────────────────────────────────────────
# Global exception handlers
# ─────────────────────────────────────────────────────────────

@app.exception_handler(LogistiQError)
async def logistiq_error_handler(request: Request, exc: LogistiQError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    log.warning(
        "logistiq.domain_error",
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
        path=request.url.path,
        trace_id=trace_id,
    )
    body = exc.to_dict()
    body["trace_id"] = trace_id
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    log.warning(
        "validation.error",
        errors=exc.errors(),
        path=request.url.path,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Request validation failed",
            "detail": exc.errors(),
            "trace_id": trace_id,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    log.error(
        "unhandled.exception",
        error=str(exc),
        exc_info=True,
        path=request.url.path,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
            "trace_id": trace_id,
        },
    )


# ─────────────────────────────────────────────────────────────
# API Routers
# ─────────────────────────────────────────────────────────────

from api.auth_routes import router as auth_router
from api.shipment_routes import router as shipment_router, carrier_router
from api.disruption_routes import router as disruption_router
from api.analytics_routes import router as analytics_router
from api.billing_routes import router as billing_router
from api.simulation_routes import router as simulation_router
from api.websocket_routes import router as ws_router

app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
app.include_router(shipment_router, prefix="/api/v1", tags=["shipments"])
app.include_router(carrier_router, prefix="/api/v1", tags=["carriers"])
app.include_router(disruption_router, prefix="/api/v1", tags=["disruptions"])
app.include_router(analytics_router, prefix="/api/v1", tags=["analytics"])
app.include_router(billing_router, prefix="/api/v1", tags=["billing"])
app.include_router(simulation_router, prefix="/api/v1", tags=["simulation"])
app.include_router(ws_router, tags=["websocket"])


# ─────────────────────────────────────────────────────────────
# MCP Routers  (each MCPServer exposes .router with its prefix baked in)
# ─────────────────────────────────────────────────────────────

from mcp_servers.mcp_weather import weather_mcp
from mcp_servers.mcp_satellite import satellite_mcp
from mcp_servers.mcp_routing import routing_mcp
from mcp_servers.mcp_shipment import shipment_mcp
from mcp_servers.mcp_notify import notify_mcp

app.include_router(weather_mcp.router, tags=["mcp"])
app.include_router(satellite_mcp.router, tags=["mcp"])
app.include_router(routing_mcp.router, tags=["mcp"])
app.include_router(shipment_mcp.router, tags=["mcp"])
app.include_router(notify_mcp.router, tags=["mcp"])


# ─────────────────────────────────────────────────────────────
# Health endpoint — matched by Docker HEALTHCHECK
# ─────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health_check() -> dict:
    """Liveness probe — returns 200 as long as the process is running.
    Also reports DB and Redis connectivity for readiness checks.
    """
    db_status = "unknown"
    redis_status = "unknown"

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:  # noqa: BLE001
        db_status = "error"

    try:
        from core.redis import redis_client
        await redis_client.ping()
        redis_status = "connected"
    except Exception:  # noqa: BLE001
        redis_status = "error"

    return {
        "status": "ok",
        "env": settings.ENVIRONMENT,
        "ts": datetime.now(timezone.utc).isoformat(),
        "db": db_status,
        "redis": redis_status,
        "sentinel": "running" if getattr(app.state, "sentinel", None) else "stopped",
        "phase_2_enabled": getattr(settings, "PHASE_2_ENABLED", False)
    }

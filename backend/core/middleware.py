"""
core/middleware.py — Request lifecycle middleware for LogistiQ AI.

TenantMiddleware responsibilities (in order):
  1. Generate / propagate request_id + trace_id tracing headers.
  2. Bind those IDs into the structlog async context so every log line
     emitted during the request carries them automatically.
  3. Extract tenant_id from the Bearer JWT (best-effort — auth routes
     that don't require a token still pass through cleanly).
  4. Store tenant_id on request.state so get_db_session can pick it up
     and issue SET LOCAL app.tenant_id for PostgreSQL RLS.
  5. Add X-Request-ID / X-Trace-ID / X-Tenant-ID response headers.
  6. Clear the structlog context after the response is sent.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.auth import decode_token
from core.logging import (
    bind_request_context,
    clear_request_context,
)

log = structlog.get_logger(__name__)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # ── 1. Tracing identifiers ────────────────────────────
        # Honour an incoming X-Trace-ID so distributed traces propagate.
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        request.state.request_id = request_id
        request.state.trace_id = trace_id

        # ── 2. Bind into structlog context (async-safe) ───────
        bind_request_context(request_id=request_id, trace_id=trace_id)

        # ── 3. Extract tenant_id from JWT (best-effort) ───────
        tenant_id: str | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            try:
                payload = decode_token(token)
                tenant_id = payload.tenant_id
            except Exception:  # noqa: BLE001,S110
                # Invalid token — the auth dependency will raise 401 later.
                # We never crash the middleware on a bad token.
                pass

        if tenant_id:
            request.state.tenant_id = tenant_id
            bind_request_context(tenant_id=tenant_id)

        log.debug(
            "request.start",
            method=request.method,
            path=request.url.path,
        )

        # ── 4. Process request ────────────────────────────────
        response = await call_next(request)

        # ── 5. Response headers ───────────────────────────────
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        if tenant_id:
            response.headers["X-Tenant-ID"] = tenant_id

        log.debug(
            "request.end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )

        # ── 6. Clear context — critical for worker reuse ──────
        clear_request_context()

        return response

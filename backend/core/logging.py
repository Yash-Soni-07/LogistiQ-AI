"""
core/logging.py — Production structlog configuration for LogistiQ AI.

Sets up structlog with:
  - JSON renderer in production, coloured console renderer in development
  - Automatic trace_id / request_id / tenant_id binding per request
  - stdlib ``logging`` integration so third-party libraries (SQLAlchemy,
    uvicorn, httpx …) emit structured JSON in the same format
  - Utility context-var helpers used by TenantMiddleware and route handlers

Usage
-----
# In main.py lifespan / startup:
    from core.logging import configure_logging
    configure_logging()

# In any module:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("shipment.created", shipment_id=sid, tenant_id=tid)

# Binding per-request context (called inside TenantMiddleware):
    from core.logging import bind_request_context, clear_request_context
    bind_request_context(request_id=..., trace_id=..., tenant_id=...)
"""

from __future__ import annotations

import logging
import logging.config
import sys
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from core.config import settings


# ─────────────────────────────────────────────────────────────
# Context variables — propagated through async task chains
# ─────────────────────────────────────────────────────────────

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
_tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def bind_request_context(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Bind per-request identifiers into the async context.

    Call this at the start of every request (inside TenantMiddleware).
    The values are automatically injected into every log record for the
    lifetime of the request via the ``_inject_context_vars`` processor.
    """
    if request_id is not None:
        _request_id_var.set(request_id)
    if trace_id is not None:
        _trace_id_var.set(trace_id)
    if tenant_id is not None:
        _tenant_id_var.set(tenant_id)
    if user_id is not None:
        _user_id_var.set(user_id)


def clear_request_context() -> None:
    """Reset all context vars.  Call at end of request in middleware."""
    _request_id_var.set(None)
    _trace_id_var.set(None)
    _tenant_id_var.set(None)
    _user_id_var.set(None)


def get_request_id() -> str | None:
    return _request_id_var.get()


def get_trace_id() -> str | None:
    return _trace_id_var.get()


def get_tenant_id() -> str | None:
    return _tenant_id_var.get()


def get_user_id() -> str | None:
    return _user_id_var.get()


# ─────────────────────────────────────────────────────────────
# Custom structlog processors
# ─────────────────────────────────────────────────────────────


def _inject_context_vars(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Structlog processor: inject async context vars into every log event."""
    if (rid := _request_id_var.get()) is not None:
        event_dict.setdefault("request_id", rid)
    if (tid := _trace_id_var.get()) is not None:
        event_dict.setdefault("trace_id", tid)
    if (tenant := _tenant_id_var.get()) is not None:
        event_dict.setdefault("tenant_id", tenant)
    if (uid := _user_id_var.get()) is not None:
        event_dict.setdefault("user_id", uid)
    return event_dict


def _add_service_metadata(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add static service-level metadata to every record."""
    event_dict.setdefault("service", "logistiq-ai-backend")
    event_dict.setdefault("env", settings.ENVIRONMENT)
    return event_dict


def _drop_color_message(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Drop uvicorn's ``color_message`` key to keep JSON clean."""
    event_dict.pop("color_message", None)
    return event_dict


# ─────────────────────────────────────────────────────────────
# Main configuration entry point
# ─────────────────────────────────────────────────────────────


def configure_logging() -> None:
    """Configure structlog + stdlib logging.

    Call **once** at application startup (inside the FastAPI lifespan or at
    module level in main.py).  Idempotent — safe to call multiple times.
    """
    is_production = settings.ENVIRONMENT not in ("development", "dev", "local")

    # ── Shared processors (run for every log record) ──────────
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,   # structlog's own context var support
        _inject_context_vars,                       # our request-scoped context vars
        _add_service_metadata,
        _drop_color_message,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if is_production:
        # ── Production: pure JSON — plays nice with Cloud Logging / Datadog ──
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        # ── Development: coloured, human-friendly console output ──────────────
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if not is_production else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ── Wire stdlib logging → structlog so uvicorn/SQLAlchemy/httpx get the same format
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Avoid duplicate handlers if called more than once
    root_logger.handlers = [h for h in root_logger.handlers if not isinstance(h, logging.StreamHandler)]
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if not is_production else logging.INFO)

    # ── Silence noisy third-party loggers ────────────────────
    for noisy in (
        "uvicorn.access",         # access logs handled separately
        "sqlalchemy.engine",      # set to WARNING; change to INFO to see SQL
        "httpx",
        "httpcore",
    ):
        logging.getLogger(noisy).setLevel(
            logging.WARNING if not is_production else logging.ERROR
        )

    # Allow SQLAlchemy pool events at WARNING
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

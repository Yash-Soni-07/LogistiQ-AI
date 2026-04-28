"""
core/exceptions.py — Centralised custom exception hierarchy for LogistiQ AI.

All exceptions translate directly to HTTP responses via the exception handlers
registered in main.py. No route handler should raise raw HTTPException for
domain errors — use these typed exceptions instead so the error contract is
machine-readable and consistent across every API surface.

Exception → HTTP status mapping
────────────────────────────────
LogistiQError          (base)      → 500
NotFoundError          (404)       → 404
ConflictError          (409)       → 409
UnauthorizedError      (401)       → 401
ForbiddenError         (403)       → 403
ValidationError        (422)       → 422
RateLimitError         (429)       → 429
ExternalServiceError   (502)       → 502
TenantIsolationError   (403)       → 403
MCPToolError           (422)       → 422  (re-exported from mcp_servers/base.py concept)
"""

from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────


class LogistiQError(Exception):
    """Root exception for all LogistiQ AI domain errors.

    Attributes
    ----------
    message     : Human-readable description of the error.
    detail      : Optional structured payload (will appear in the JSON body).
    status_code : HTTP status to respond with (default 500).
    error_code  : Machine-readable slug, e.g. ``"shipment_not_found"``.
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        *,
        detail: Any = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        if error_code:
            self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the standard error envelope returned by exception handlers."""
        payload: dict[str, Any] = {
            "error": self.error_code,
            "message": self.message,
        }
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


# ─────────────────────────────────────────────────────────────
# 4xx Client errors
# ─────────────────────────────────────────────────────────────


class NotFoundError(LogistiQError):
    """Raised when a requested resource does not exist.

    Example: shipment ID not found for this tenant.
    """

    status_code = 404
    error_code = "not_found"

    def __init__(
        self,
        resource: str = "Resource",
        resource_id: str | None = None,
        *,
        detail: Any = None,
    ) -> None:
        msg = f"{resource} not found"
        if resource_id:
            msg = f"{resource} '{resource_id}' not found"
        super().__init__(msg, detail=detail, error_code=self.error_code)
        self.resource = resource
        self.resource_id = resource_id


class ConflictError(LogistiQError):
    """Raised when an action would violate a uniqueness / state constraint.

    Example: email already registered, duplicate shipment tracking number.
    """

    status_code = 409
    error_code = "conflict"

    def __init__(
        self,
        message: str = "Resource already exists or conflicts with existing data",
        *,
        detail: Any = None,
    ) -> None:
        super().__init__(message, detail=detail, error_code=self.error_code)


class UnauthorizedError(LogistiQError):
    """Raised when a request arrives without valid authentication credentials.

    Example: missing or expired JWT.
    """

    status_code = 401
    error_code = "unauthorized"

    def __init__(
        self,
        message: str = "Authentication required",
        *,
        detail: Any = None,
    ) -> None:
        super().__init__(message, detail=detail, error_code=self.error_code)


class ForbiddenError(LogistiQError):
    """Raised when a valid user lacks permission for the requested action.

    Example: VIEWER role attempting to update a shipment.
    """

    status_code = 403
    error_code = "forbidden"

    def __init__(
        self,
        message: str = "Insufficient permissions for this action",
        *,
        required_role: str | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message, detail=detail, error_code=self.error_code)
        self.required_role = required_role


class TenantIsolationError(LogistiQError):
    """Raised when a tenant attempts to access another tenant's data.

    This is treated more seriously than ForbiddenError — it indicates a
    potential data-isolation breach and should be logged at ERROR level.
    """

    status_code = 403
    error_code = "tenant_isolation_violation"

    def __init__(
        self,
        message: str = "Cross-tenant access denied",
        *,
        tenant_id: str | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message, detail=detail, error_code=self.error_code)
        self.tenant_id = tenant_id


class ValidationError(LogistiQError):
    """Raised when business-rule validation fails (distinct from Pydantic schema errors).

    Example: a shipment weight exceeds carrier maximum, invalid date range.
    """

    status_code = 422
    error_code = "validation_error"

    def __init__(
        self,
        message: str = "Validation failed",
        *,
        field: str | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message, detail=detail, error_code=self.error_code)
        self.field = field

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.field:
            payload["field"] = self.field
        return payload


class RateLimitError(LogistiQError):
    """Raised when a client exceeds allowed request frequency.

    Example: > 5 failed login attempts per minute (backed by Redis counter).
    """

    status_code = 429
    error_code = "rate_limit_exceeded"

    def __init__(
        self,
        message: str = "Too many requests. Please slow down.",
        *,
        retry_after_seconds: int | None = 60,
        detail: Any = None,
    ) -> None:
        super().__init__(message, detail=detail, error_code=self.error_code)
        self.retry_after_seconds = retry_after_seconds

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        return payload


# ─────────────────────────────────────────────────────────────
# 5xx Server / upstream errors
# ─────────────────────────────────────────────────────────────


class ExternalServiceError(LogistiQError):
    """Raised when an upstream dependency (MCP, Open-Meteo, USGS, Stripe …)
    returns an error or times out.

    Results in a 502 Bad Gateway so clients know the issue is upstream.
    """

    status_code = 502
    error_code = "external_service_error"

    def __init__(
        self,
        service: str = "External service",
        message: str | None = None,
        *,
        detail: Any = None,
    ) -> None:
        msg = message or f"{service} is currently unavailable"
        super().__init__(msg, detail=detail, error_code=self.error_code)
        self.service = service

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["service"] = self.service
        return payload


class DatabaseError(LogistiQError):
    """Raised for unexpected database failures (not expected not-found cases).

    These are always 500 — clients should not see raw DB error messages.
    """

    status_code = 500
    error_code = "database_error"

    def __init__(
        self,
        message: str = "A database error occurred",
        *,
        detail: Any = None,
    ) -> None:
        super().__init__(message, detail=detail, error_code=self.error_code)


class AgentError(LogistiQError):
    """Raised when an AI agent (sentinel, decision, copilot) fails to complete.

    Example: Gemini API key missing, LangGraph graph execution failure.
    """

    status_code = 500
    error_code = "agent_error"

    def __init__(
        self,
        agent: str = "Agent",
        message: str | None = None,
        *,
        detail: Any = None,
    ) -> None:
        msg = message or f"{agent} failed to complete the requested action"
        super().__init__(msg, detail=detail, error_code=self.error_code)
        self.agent = agent

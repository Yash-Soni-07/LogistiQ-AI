"""tests/unit/test_exceptions.py — Exception hierarchy and contract tests."""

from __future__ import annotations

import pytest

from core.exceptions import (
    AgentError,
    ConflictError,
    DatabaseError,
    ExternalServiceError,
    ForbiddenError,
    LogistiQError,
    NotFoundError,
    RateLimitError,
    TenantIsolationError,
    UnauthorizedError,
    ValidationError,
)


# ── Hierarchy ─────────────────────────────────────────────────

def test_all_subclass_logistiq_error():
    for cls in (
        NotFoundError, ConflictError, UnauthorizedError, ForbiddenError,
        TenantIsolationError, ValidationError, RateLimitError,
        ExternalServiceError, DatabaseError, AgentError,
    ):
        assert issubclass(cls, LogistiQError), f"{cls} should subclass LogistiQError"


# ── Status codes ──────────────────────────────────────────────

@pytest.mark.parametrize("cls,code", [
    (NotFoundError, 404),
    (ConflictError, 409),
    (UnauthorizedError, 401),
    (ForbiddenError, 403),
    (TenantIsolationError, 403),
    (ValidationError, 422),
    (RateLimitError, 429),
    (ExternalServiceError, 502),
    (DatabaseError, 500),
    (AgentError, 500),
])
def test_status_codes(cls, code):
    assert cls().status_code == code


# ── to_dict contracts ─────────────────────────────────────────

def test_not_found_to_dict_contains_id():
    d = NotFoundError("Shipment", "abc-123").to_dict()
    assert d["error"] == "not_found"
    assert "abc-123" in d["message"]
    assert "Shipment" in d["message"]


def test_not_found_without_id():
    d = NotFoundError("Carrier").to_dict()
    assert "Carrier" in d["message"]
    assert "None" not in d["message"]


def test_rate_limit_to_dict_has_retry_after():
    d = RateLimitError(retry_after_seconds=30).to_dict()
    assert d["retry_after_seconds"] == 30


def test_rate_limit_default_retry_after():
    d = RateLimitError().to_dict()
    assert d["retry_after_seconds"] == 60


def test_external_service_to_dict_has_service():
    """ExternalServiceError should include the failing service in the payload."""
    d = ExternalServiceError("Razorpay", message="Rate limited").to_dict()
    assert d["service"] == "Razorpay"


def test_external_service_custom_message():
    d = ExternalServiceError("Razorpay", message="Rate limited").to_dict()
    assert d["message"] == "Rate limited"


def test_validation_error_to_dict_has_field():
    d = ValidationError("Bad weight", field="weight_kg").to_dict()
    assert d["field"] == "weight_kg"
    assert d["message"] == "Bad weight"


def test_validation_error_no_field():
    d = ValidationError("Oops").to_dict()
    assert "field" not in d


def test_tenant_isolation_error_code():
    exc = TenantIsolationError(tenant_id="t-123")
    assert exc.error_code == "tenant_isolation_violation"
    assert exc.tenant_id == "t-123"


def test_agent_error_includes_agent():
    exc = AgentError("SentinelAgent", "Gemini timeout")
    assert exc.agent == "SentinelAgent"
    assert "Gemini timeout" in exc.message


def test_forbidden_required_role():
    exc = ForbiddenError(required_role="admin")
    assert exc.required_role == "admin"


def test_base_error_custom_error_code():
    exc = LogistiQError("Custom", error_code="my_custom_code")
    assert exc.error_code == "my_custom_code"
    assert exc.to_dict()["error"] == "my_custom_code"


def test_detail_included_in_to_dict():
    exc = NotFoundError("Shipment", detail={"extra": "info"})
    d = exc.to_dict()
    assert d["detail"] == {"extra": "info"}

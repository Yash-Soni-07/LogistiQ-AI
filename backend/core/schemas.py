"""
core/schemas.py — Pydantic v2 schemas for LogistiQ AI.

Every schema uses model_config = ConfigDict(from_attributes=True) so
SQLAlchemy ORM objects can be serialized directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")

# Deferred import to avoid circular dependency: models → schemas → models
from db.models import DisruptionSeverity, DisruptionType  # noqa: E402

# ─────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────


class TokenPayload(BaseModel):
    user_id: str
    tenant_id: str
    role: str = "viewer"
    type: str = "access"
    exp: int
    jti: str | None = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    company_name: str = Field(min_length=1, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    """Payload for POST /auth/google — frontend sends the Google OAuth access_token."""

    access_token: str
    company_name: str | None = None  # Used for tenant creation on first Google sign-up


# ─────────────────────────────────────────────────────────────
# Tenant & User
# ─────────────────────────────────────────────────────────────


class TenantProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    plan_tier: str = "starter"
    is_active: bool = True
    created_at: datetime


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None = None
    role: str
    is_active: bool = True
    tenant_id: str
    tenant: TenantProfile | None = None
    created_at: datetime
    last_login: datetime | None = None


# ─────────────────────────────────────────────────────────────
# Pagination
# ─────────────────────────────────────────────────────────────


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(from_attributes=True)

    total: int
    offset: int
    limit: int
    items: list[Any]  # ORM objects serialized by route's response_model


# ─────────────────────────────────────────────────────────────
# Shipments
# ─────────────────────────────────────────────────────────────


class ShipmentCreate(BaseModel):
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    sector: str | None = None
    mode: str = "road"
    carrier_id: str | None = None
    weight_kg: float | None = None
    volume_m3: float | None = None
    temperature_c: float | None = None
    sla_deadline: datetime | None = None
    estimated_delivery: datetime | None = None
    actual_delivery: datetime | None = None


class ShipmentUpdate(BaseModel):
    status: str | None = None
    mode: str | None = None
    carrier_id: str | None = None
    eta_current: datetime | None = None
    risk_score: float | None = None
    current_lat: float | None = None
    current_lon: float | None = None


class ShipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    tenant_id: str
    tracking_num: str | None = None
    origin: str
    destination: str
    current_lat: float | None = None
    current_lon: float | None = None
    status: str
    mode: str
    sector: str | None = None
    risk_score: float = 0.0
    carrier_id: str | None = None
    route_id: str | None = None
    sla_deadline: datetime | None = None
    eta_current: datetime | None = None
    co2_kg: float = 0.0
    weight_kg: float | None = None
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────
# Carriers
# ─────────────────────────────────────────────────────────────


class CarrierCreate(BaseModel):
    name: str = Field(min_length=1)
    modes: list[str] = Field(default_factory=list)
    rating: float = Field(default=0.0, ge=0.0, le=5.0)
    cost_per_km: float = Field(default=0.0, ge=0.0)
    co2_per_tonne_km: float = Field(default=18.0, ge=0.0)


class CarrierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    tenant_id: str
    name: str
    modes: list[str] = Field(default_factory=list)
    rating: float = 0.0
    avg_delay_h: float = 0.0
    cost_per_km: float = 0.0
    co2_per_tonne_km: float = 18.0
    available_now: bool = True
    verified_at: datetime | None = None
    created_at: datetime


# ─────────────────────────────────────────────────────────────
# Disruptions
# ─────────────────────────────────────────────────────────────


class DisruptionCreate(BaseModel):
    type: DisruptionType
    severity: DisruptionSeverity = DisruptionSeverity.MEDIUM
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=10.0, gt=0)
    description: str | None = None
    impact: str | None = None  # optional human-readable impact summary


class DisruptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    type: str
    severity: str
    radius_km: float = 10.0
    risk_score: float = 0.0
    source_apis: list[str] = Field(default_factory=list)
    source_count: int = 1
    affected_segment_ids: list[str] = Field(default_factory=list)
    status: str = "active"
    auto_handled: bool = False
    resolved_at: datetime | None = None
    created_at: datetime


# ─────────────────────────────────────────────────────────────
# Billing
# ─────────────────────────────────────────────────────────────


class BillingStatusRead(BaseModel):
    plan_tier: str
    status: str
    razorpay_customer_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SubscribeRequest(BaseModel):
    plan_tier: str
    trial_days: int = 14


class ChangePlanRequest(BaseModel):
    plan_tier: str


# ─────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    env: str
    ts: datetime
    db: str = "unknown"
    redis: str = "unknown"

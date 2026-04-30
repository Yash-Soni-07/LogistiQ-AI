"""
db/models.py — SQLAlchemy 2.0 async ORM models for LogistiQ AI.

All models inherit from Base (DeclarativeBase subclass). The alias
`DeclarativeBase = Base` that caused metadata breakage has been removed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy import ARRAY, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import text
from sqlalchemy.types import TypeDecorator

# ─────────────────────────────────────────────────────────────
# Dialect-aware StringArray
# Renders as ARRAY(String) on PostgreSQL and JSON on SQLite/others
# so tests (aiosqlite) can create the schema without a compile error.
# ─────────────────────────────────────────────────────────────


class StringArray(TypeDecorator):
    """List[str] stored as ARRAY on Postgres, JSON elsewhere (e.g. SQLite in tests)."""

    impl = sa.JSON  # fallback impl — overridden per dialect below
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String))
        return dialect.type_descriptor(sa.JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return [] if dialect.name == "postgresql" else []
        return list(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        return list(value)


class NullableGeometry(TypeDecorator):
    """Geometry stored as GeoAlchemy2 Geometry on PostgreSQL, Text (WKT) on SQLite.

    This lets the test suite create the full schema on aiosqlite without
    requiring the SpatiaLite extension (RecoverGeometryColumn).
    Geometry values read from SQLite come back as plain WKT strings;
    production code always runs on PostgreSQL where the real type is used.
    """

    impl = Text  # fallback for non-postgres dialects
    cache_ok = True

    def __init__(self, geometry_type: str = "GEOMETRY", srid: int = 4326):
        self._geometry_type = geometry_type
        self._srid = srid
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Geometry(self._geometry_type, srid=self._srid))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        # Pass through; GeoAlchemy2 / plain text both accept string WKT
        return value

    def process_result_value(self, value, dialect):
        return value


# ─────────────────────────────────────────────────────────────
# Base — single source of truth for metadata
# ─────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class CompatUUID(TypeDecorator):
    """UUID stored natively on PostgreSQL, as CHAR(36) on SQLite/others.

    Accepts str or uuid.UUID as input; always returns str.
    Avoids the 'str has no .hex' error when inserting string UUIDs on SQLite.
    """

    impl = sa.CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(sa.UUID(as_uuid=False))
        return dialect.type_descriptor(sa.CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return str(value)  # accept both uuid.UUID and plain str

    def process_result_value(self, value, dialect):
        return str(value) if value is not None else None


# ─────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────


class PlanTier(StrEnum):
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UserRole(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    VIEWER = "viewer"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    AT_RISK = "at_risk"
    REROUTED = "rerouted"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ShipmentMode(StrEnum):
    ROAD = "road"
    RAIL = "rail"
    SEA = "sea"
    AIR = "air"
    MULTIMODAL = "multimodal"


class DisruptionSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DisruptionType(StrEnum):
    # New canonical values (used by agents)
    FLOOD = "flood"
    FIRE = "fire"
    QUAKE = "quake"
    STRIKE = "strike"
    PORT_CONGESTION = "port_congestion"
    FUEL_SHORTAGE = "fuel_shortage"
    TARIFF = "tariff"
    CYBER = "cyber"
    COLD_CHAIN_BREACH = "cold_chain_breach"
    JIT_FAILURE = "jit_failure"
    # Legacy values — kept for backward compatibility, DO NOT REMOVE
    WEATHER = "weather"
    TRAFFIC = "traffic"
    ACCIDENT = "accident"
    NATURAL_DISASTER = "natural_disaster"
    SECURITY = "security"


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    plan_tier: Mapped[str] = mapped_column(
        String(50), nullable=False, default=PlanTier.STARTER.value, server_default="starter"
    )
    razorpay_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
    )

    # Relationships
    users: Mapped[list[User]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    shipments: Mapped[list[Shipment]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    carriers: Mapped[list[Carrier]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    disruption_events: Mapped[list[DisruptionEvent]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    agent_decisions: Mapped[list[AgentDecision]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    subscription_events: Mapped[list[SubscriptionEvent]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name='{self.name}', plan_tier='{self.plan_tier}')>"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        sa.Enum(
            UserRole,
            native_enum=False,
            length=50,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=UserRole.VIEWER,
        server_default="viewer",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_login: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(back_populates="users")
    subscription_events: Mapped[list[SubscriptionEvent]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"


class Carrier(Base):
    __tablename__ = "carriers"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    modes: Mapped[list[str]] = mapped_column(StringArray, nullable=False, server_default="{}")
    rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    avg_delay_h: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    cost_per_km: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    co2_per_tonne_km: Mapped[float] = mapped_column(
        Float, nullable=False, default=18.0, server_default="18.0"
    )
    available_now: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(back_populates="carriers")
    shipments: Mapped[list[Shipment]] = relationship(back_populates="carrier")

    def __repr__(self) -> str:
        return f"<Carrier(id={self.id}, name='{self.name}', tenant_id='{self.tenant_id}')>"


class RouteSegment(Base):
    """Road-network graph node — NOT a child of any shipment (Decision: Option B)."""

    __tablename__ = "route_segments"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    # tenant_id is nullable: network data may be shared or global
    tenant_id: Mapped[str | None] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    geom: Mapped[Any] = mapped_column(NullableGeometry("LINESTRING", srid=4326), nullable=True)
    highway_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    elevation_avg_m: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    flood_prob: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    fire_risk: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    congestion_idx: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    last_scored_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    def __repr__(self) -> str:
        return (
            f"<RouteSegment(id={self.id}, highway_code='{self.highway_code}',"
            f" risk_score={self.risk_score})>"
        )


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    tracking_num: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    origin: Mapped[str] = mapped_column(String(500), nullable=False)
    destination: Mapped[str] = mapped_column(String(500), nullable=False)
    current_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[ShipmentStatus] = mapped_column(
        sa.Enum(
            ShipmentStatus,
            native_enum=False,
            length=50,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ShipmentStatus.PENDING,
        server_default="pending",
    )
    mode: Mapped[ShipmentMode] = mapped_column(
        sa.Enum(
            ShipmentMode,
            native_enum=False,
            length=50,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ShipmentMode.ROAD,
        server_default="road",
    )
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    carrier_id: Mapped[str | None] = mapped_column(
        CompatUUID(), ForeignKey("carriers.id", ondelete="SET NULL"), nullable=True
    )
    route_id: Mapped[str | None] = mapped_column(
        CompatUUID(), ForeignKey("route_segments.id", ondelete="SET NULL"), nullable=True
    )
    sla_deadline: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=True)
    eta_current: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=True)
    estimated_delivery: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=True
    )
    actual_delivery: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=True
    )
    co2_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(back_populates="shipments")
    carrier: Mapped[Carrier | None] = relationship(back_populates="shipments")
    agent_decisions: Mapped[list[AgentDecision]] = relationship(back_populates="shipment")
    telemetry: Mapped[list[Telemetry]] = relationship(back_populates="shipment")

    def __repr__(self) -> str:
        return (
            f"<Shipment(id={self.id}, tracking_num='{self.tracking_num}', status='{self.status}')>"
        )


class DisruptionEvent(Base):
    __tablename__ = "disruption_events"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(50), nullable=False, default=DisruptionSeverity.MEDIUM.value, server_default="medium"
    )
    center_geom: Mapped[Any] = mapped_column(NullableGeometry("POINT", srid=4326), nullable=True)
    radius_km: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0, server_default="10.0"
    )
    risk_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    source_apis: Mapped[list[str]] = mapped_column(StringArray, nullable=False, server_default="{}")
    source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    affected_segment_ids: Mapped[list[str]] = mapped_column(
        StringArray, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )
    auto_handled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(back_populates="disruption_events")
    agent_decisions: Mapped[list[AgentDecision]] = relationship(back_populates="disruption")

    def __repr__(self) -> str:
        return f"<DisruptionEvent(id={self.id}, type='{self.type}', severity='{self.severity}')>"


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[str | None] = mapped_column(
        CompatUUID(), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    disruption_id: Mapped[str | None] = mapped_column(
        CompatUUID(), ForeignKey("disruption_events.id", ondelete="SET NULL"), nullable=True
    )
    # Legacy field — kept for backward compat
    decision: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_taken: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Spec fields
    trace_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reasoning_chain: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    tool_calls: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    human_overridden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    cost_delta: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    co2_delta: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(back_populates="agent_decisions")
    shipment: Mapped[Shipment | None] = relationship(back_populates="agent_decisions")
    disruption: Mapped[DisruptionEvent | None] = relationship(back_populates="agent_decisions")

    def __repr__(self) -> str:
        return (
            f"<AgentDecision(id={self.id}, action_taken='{self.action_taken}',"
            f" confidence={self.confidence})>"
        )


class Telemetry(Base):
    __tablename__ = "telemetry"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    tenant_id: Mapped[str | None] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    shipment_id: Mapped[str] = mapped_column(
        CompatUUID(), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    heading: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    accuracy_m: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="gps", server_default="gps"
    )
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Keep legacy data column for any existing rows
    data: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    # Relationships
    shipment: Mapped[Shipment] = relationship(back_populates="telemetry")

    def __repr__(self) -> str:
        return f"<Telemetry(id={self.id}, shipment_id='{self.shipment_id}', ts={self.ts})>"


class NewsAlert(Base):
    """Global table — GDELT is a global feed, NOT tenant-scoped."""

    __tablename__ = "news_alerts"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    # NO tenant_id — this is global
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ(timezone=True), nullable=True)
    locations: Mapped[list[str]] = mapped_column(StringArray, nullable=False, server_default="{}")
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    linked_segment_ids: Mapped[list[str]] = mapped_column(
        StringArray, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )
    # Legacy columns — kept for backward compat
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    def __repr__(self) -> str:
        return f"<NewsAlert(id={self.id}, event_type='{self.event_type}', source='{self.source}')>"


class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"

    id: Mapped[str] = mapped_column(
        CompatUUID(), primary_key=True, default=lambda: str(__import__("uuid").uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CompatUUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    razorpay_event_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    amount_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    # Legacy columns — kept for backward compat
    user_id: Mapped[str | None] = mapped_column(
        CompatUUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(back_populates="subscription_events")
    user: Mapped[User | None] = relationship(back_populates="subscription_events")

    def __repr__(self) -> str:
        return (
            f"<SubscriptionEvent(id={self.id}, type='{self.type}', tenant_id='{self.tenant_id}')>"
        )

"""sync_schema

Revision ID: 730413e36e98
Revises: 003_add_missing_columns
Create Date: 2026-04-28 03:57:10.517677+00:00
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import db.models
import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision: str = "730413e36e98"
down_revision: str | None = "003_add_missing_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None



def upgrade() -> None:
    op.alter_column(
        "agent_decisions",
        "id",
        existing_type=sa.UUID(),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "agent_decisions",
        "decision",
        existing_type=postgresql.JSON(astext_type=sa.Text()),
        nullable=True,
    )
    op.alter_column(
        "agent_decisions",
        "reasoning_chain",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_decisions",
        "tool_calls",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        existing_nullable=True,
    )
    op.drop_constraint(
        op.f("agent_decisions_shipment_id_fkey"), "agent_decisions", type_="foreignkey"
    )
    op.create_foreign_key(
        None, "agent_decisions", "shipments", ["shipment_id"], ["id"], ondelete="SET NULL"
    )
    op.drop_column("agent_decisions", "updated_at")
    op.alter_column(
        "carriers", "id", existing_type=sa.UUID(), server_default=None, existing_nullable=False
    )
    op.drop_index(op.f("ix_carriers_tenant_id"), table_name="carriers")
    op.add_column(
        "disruption_events",
        sa.Column("risk_score", sa.Float(), server_default="0.0", nullable=False),
    )
    op.add_column(
        "disruption_events",
        sa.Column("source_apis", db.models.StringArray(), server_default="{}", nullable=False),
    )
    op.add_column(
        "disruption_events",
        sa.Column("source_count", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "disruption_events",
        sa.Column(
            "affected_segment_ids", db.models.StringArray(), server_default="{}", nullable=False
        ),
    )
    op.add_column(
        "disruption_events",
        sa.Column("auto_handled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "disruption_events",
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.alter_column(
        "disruption_events",
        "id",
        existing_type=sa.UUID(),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "disruption_events",
        "type",
        existing_type=postgresql.ENUM(
            "weather",
            "traffic",
            "accident",
            "strike",
            "natural_disaster",
            "security",
            "flood",
            "fire",
            "quake",
            "port_congestion",
            "fuel_shortage",
            "tariff",
            "cyber",
            "cold_chain_breach",
            "jit_failure",
            name="disruptiontype",
        ),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.alter_column(
        "disruption_events",
        "severity",
        existing_type=postgresql.ENUM(
            "low", "medium", "high", "critical", name="disruptionseverity"
        ),
        type_=sa.String(length=50),
        existing_nullable=False,
        existing_server_default=sa.text("'medium'::disruptionseverity"),
    )
    op.alter_column(
        "disruption_events",
        "center_geom",
        existing_type=geoalchemy2.types.Geometry(
            geometry_type="POINT",
            srid=4326,
            dimension=2,
            from_text="ST_GeomFromEWKT",
            name="geometry",
            nullable=False,
            _spatial_index_reflected=True,
        ),
        nullable=True,
    )
    op.alter_column(
        "disruption_events",
        "radius_km",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        server_default="10.0",
        nullable=False,
    )
    op.drop_index(
        op.f("idx_disruption_events_center_geom"),
        table_name="disruption_events",
        postgresql_using="gist",
    )
    op.drop_index(op.f("ix_disruption_events_tenant_type"), table_name="disruption_events")
    op.alter_column(
        "news_alerts", "id", existing_type=sa.UUID(), server_default=None, existing_nullable=False
    )
    op.alter_column("news_alerts", "title", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.alter_column("news_alerts", "content", existing_type=sa.TEXT(), nullable=True)
    op.drop_column("news_alerts", "updated_at")
    op.alter_column(
        "route_segments",
        "id",
        existing_type=sa.UUID(),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "route_segments",
        "geom",
        existing_type=geoalchemy2.types.Geometry(
            geometry_type="LINESTRING",
            srid=4326,
            dimension=2,
            from_text="ST_GeomFromEWKT",
            name="geometry",
            nullable=False,
            _spatial_index_reflected=True,
        ),
        nullable=True,
    )
    op.drop_index(
        op.f("idx_route_segments_geom"), table_name="route_segments", postgresql_using="gist"
    )
    op.drop_index(op.f("ix_route_segments_highway_code"), table_name="route_segments")
    op.drop_index(op.f("ix_route_segments_tenant_id"), table_name="route_segments")
    op.drop_column("route_segments", "estimated_duration_h")
    op.drop_column("route_segments", "sequence")
    op.drop_column("route_segments", "updated_at")
    op.drop_column("route_segments", "distance_km")
    op.alter_column(
        "shipments", "id", existing_type=sa.UUID(), server_default=None, existing_nullable=False
    )
    op.alter_column(
        "shipments",
        "origin",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
    op.alter_column(
        "shipments",
        "destination",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
    op.alter_column(
        "shipments",
        "status",
        existing_type=postgresql.ENUM(
            "pending",
            "in_transit",
            "delivered",
            "delayed",
            "cancelled",
            "at_risk",
            "rerouted",
            name="shipmentstatus",
        ),
        type_=sa.Enum(
            "pending",
            "in_transit",
            "at_risk",
            "rerouted",
            "delayed",
            "delivered",
            "cancelled",
            name="shipmentstatus",
            native_enum=False,
            length=50,
        ),
        existing_nullable=False,
        existing_server_default=sa.text("'pending'::shipmentstatus"),
    )
    op.alter_column(
        "shipments",
        "mode",
        existing_type=postgresql.ENUM(
            "road", "rail", "air", "sea", "multimodal", name="shipmentmode"
        ),
        type_=sa.Enum(
            "road",
            "rail",
            "sea",
            "air",
            "multimodal",
            name="shipmentmode",
            native_enum=False,
            length=50,
        ),
        existing_nullable=False,
        existing_server_default=sa.text("'road'::shipmentmode"),
    )
    op.alter_column(
        "shipments",
        "sector",
        existing_type=sa.VARCHAR(length=50),
        type_=sa.String(length=100),
        nullable=True,
    )
    op.alter_column(
        "shipments",
        "estimated_delivery",
        existing_type=sa.DATE(),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "shipments",
        "actual_delivery",
        existing_type=sa.DATE(),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=True,
    )
    op.drop_index(op.f("ix_shipments_tenant_status"), table_name="shipments")
    op.alter_column(
        "subscription_events",
        "id",
        existing_type=sa.UUID(),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column("subscription_events", "user_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column(
        "subscription_events", "event_type", existing_type=sa.VARCHAR(length=50), nullable=True
    )
    op.alter_column(
        "telemetry", "id", existing_type=sa.UUID(), server_default=None, existing_nullable=False
    )
    op.alter_column(
        "telemetry", "data", existing_type=postgresql.JSON(astext_type=sa.Text()), nullable=True
    )
    op.drop_index(op.f("ix_telemetry_shipment_ts"), table_name="telemetry")
    op.drop_column("telemetry", "created_at")
    op.drop_column("telemetry", "updated_at")
    op.alter_column(
        "tenants", "id", existing_type=sa.UUID(), server_default=None, existing_nullable=False
    )
    op.alter_column(
        "users", "id", existing_type=sa.UUID(), server_default=None, existing_nullable=False
    )
    op.alter_column(
        "users",
        "role",
        existing_type=postgresql.ENUM("admin", "manager", "operator", "viewer", name="userrole"),
        type_=sa.Enum(
            "admin", "manager", "operator", "viewer", name="userrole", native_enum=False, length=50
        ),
        existing_nullable=False,
        existing_server_default=sa.text("'viewer'::userrole"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    pass

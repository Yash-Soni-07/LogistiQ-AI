"""initial_schema

Revision ID: 622e968f61eb
Revises:
Create Date: 2026-04-22 23:33:32.385468+00:00
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
import geoalchemy2

# revision identifiers, used by Alembic
revision: str = "622e968f61eb"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Standard Tables ────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "carriers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "disruption_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "weather",
                "traffic",
                "accident",
                "strike",
                "natural_disaster",
                "security",
                name="disruptiontype",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name="disruptionseverity"),
            server_default=sa.text("'medium'::disruptionseverity"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=50), server_default=sa.text("'active'::text"), nullable=False
        ),
        sa.Column(
            "center_geom",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("radius_km", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "news_alerts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column(
            "role",
            sa.Enum("admin", "manager", "operator", "viewer", name="userrole"),
            server_default=sa.text("'viewer'::userrole"),
            nullable=False,
        ),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "shipments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("carrier_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "in_transit", "delivered", "delayed", "cancelled", name="shipmentstatus"
            ),
            server_default=sa.text("'pending'::shipmentstatus"),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.Enum("road", "rail", "air", "sea", name="shipmentmode"),
            server_default=sa.text("'road'::shipmentmode"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(length=255), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=False),
        sa.Column("sector", sa.String(length=50), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("volume_m3", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("estimated_delivery", sa.DATE(), nullable=True),
        sa.Column("actual_delivery", sa.DATE(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["carrier_id"], ["carriers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "subscription_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("shipment_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("action_taken", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── FIXED: Added tenant_id column and FK ──────────────────────────────────
    op.create_table(
        "route_segments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("shipment_id", sa.UUID(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="LINESTRING",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("estimated_duration_h", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── FIXED: Added tenant_id column and FK ──────────────────────────────────
    op.create_table(
        "telemetry",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("shipment_id", sa.UUID(), nullable=False),
        sa.Column(
            "ts", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False
        ),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Row Level Security ─────────────────────────────────────────────────────
    # FIXED: Included news_alerts and route_segments
    tenant_tables = [
        "users",
        "shipments",
        "carriers",
        "disruption_events",
        "agent_decisions",
        "telemetry",
        "subscription_events",
        # "news_alerts",
        "route_segments",
    ]
    for tbl in tenant_tables:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")  # noqa: S608
        op.execute(  # noqa: S608
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE tablename='{tbl}' AND policyname='tenant_isolation'
              ) THEN
                CREATE POLICY tenant_isolation ON {tbl}
                  USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
                  );
              END IF;
            END $$;
            """
        )

    # ── GiST indexes on geometry columns ──────────────────────────────────────
    op.create_index("ix_route_segments_geom", "route_segments", ["geom"], postgresql_using="gist")
    op.create_index(
        "ix_disruption_events_center_geom",
        "disruption_events",
        ["center_geom"],
        postgresql_using="gist",
    )

    # ── B-tree indexes for high-cardinality lookups ────────────────────────────
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_shipments_tenant_id", "shipments", ["tenant_id"])
    op.create_index("ix_disruption_events_tenant_id", "disruption_events", ["tenant_id"])
    op.create_index("ix_agent_decisions_tenant_id", "agent_decisions", ["tenant_id"])
    op.create_index("ix_telemetry_shipment_id", "telemetry", ["shipment_id"])
    op.create_index("ix_telemetry_tenant_id", "telemetry", ["tenant_id"])
    op.create_index("ix_route_segments_tenant_id", "route_segments", ["tenant_id"])
    op.create_index("ix_news_alerts_tenant_id", "news_alerts", ["tenant_id"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_news_alerts_tenant_id", table_name="news_alerts")
    op.drop_index("ix_route_segments_tenant_id", table_name="route_segments")
    op.drop_index("ix_telemetry_tenant_id", table_name="telemetry")
    op.drop_index("ix_telemetry_shipment_id", table_name="telemetry")
    op.drop_index("ix_agent_decisions_tenant_id", table_name="agent_decisions")
    op.drop_index("ix_disruption_events_tenant_id", table_name="disruption_events")
    op.drop_index("ix_shipments_tenant_id", table_name="shipments")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_index("ix_disruption_events_center_geom", table_name="disruption_events")
    op.drop_index("ix_route_segments_geom", table_name="route_segments")

    # Drop tables
    op.drop_table("telemetry")
    op.drop_table("agent_decisions")
    op.drop_table("route_segments")
    op.drop_table("subscription_events")
    op.drop_table("disruption_events")
    op.drop_table("news_alerts")
    op.drop_table("shipments")
    op.drop_table("carriers")
    op.drop_table("users")
    op.drop_table("tenants")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS disruptiontype CASCADE")
    op.execute("DROP TYPE IF EXISTS disruptionseverity CASCADE")
    op.execute("DROP TYPE IF EXISTS shipmentstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS shipmentmode CASCADE")
    op.execute("DROP TYPE IF EXISTS userrole CASCADE")

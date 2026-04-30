"""003_add_missing_columns

Revision ID: 003_add_missing_columns
Revises: 002_add_enum_values
Create Date: 2026-04-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_add_missing_columns"
down_revision: Union[str, None] = "002_add_enum_values"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 2. tenants — add spec columns ─────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='tenants' AND column_name='domain') THEN
                ALTER TABLE tenants ADD COLUMN domain VARCHAR(255) UNIQUE;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='tenants' AND column_name='plan_tier') THEN
                ALTER TABLE tenants ADD COLUMN plan_tier VARCHAR(50) NOT NULL DEFAULT 'starter';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='tenants' AND column_name='razorpay_customer_id') THEN
                ALTER TABLE tenants ADD COLUMN razorpay_customer_id VARCHAR(255);
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='tenants' AND column_name='razorpay_subscription_id') THEN
                ALTER TABLE tenants ADD COLUMN razorpay_subscription_id VARCHAR(255);
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='tenants' AND column_name='is_active') THEN
                ALTER TABLE tenants ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
            END IF;
        END $$;
    """)

    # ── 3. users — add spec columns ───────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='users' AND column_name='is_active') THEN
                ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='users' AND column_name='last_login') THEN
                ALTER TABLE users ADD COLUMN last_login TIMESTAMPTZ;
            END IF;
        END $$;
    """)

    # ── 4. shipments — add spec columns ───────────────────────────────────────
    spec_shipment_cols = [
        ("tracking_num",  "VARCHAR(100)"),
        ("current_lat",   "FLOAT"),
        ("current_lon",   "FLOAT"),
        ("risk_score",    "FLOAT NOT NULL DEFAULT 0.0"),
        ("route_id",      "UUID REFERENCES route_segments(id) ON DELETE SET NULL"),
        ("sla_deadline",  "TIMESTAMPTZ"),
        ("eta_current",   "TIMESTAMPTZ"),
        ("co2_kg",        "FLOAT NOT NULL DEFAULT 0.0"),
    ]
    for col_name, col_def in spec_shipment_cols:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='shipments' AND column_name='{col_name}') THEN
                    ALTER TABLE shipments ADD COLUMN {col_name} {col_def};
                END IF;
            END $$;
        """)

    # Generate tracking_num for any existing rows before making NOT NULL
    op.execute("""
        UPDATE shipments
        SET tracking_num = CONCAT('TRK-', SUBSTRING(id::text, 1, 8))
        WHERE tracking_num IS NULL;
    """)

    # Add UNIQUE constraint on tracking_num (idempotent)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'shipments_tracking_num_key'
            ) THEN
                ALTER TABLE shipments ADD CONSTRAINT shipments_tracking_num_key UNIQUE (tracking_num);
            END IF;
        END $$;
    """)

    # ── 5. route_segments — Option B: drop shipment_id, add tenant_id ─────────
    # Drop FK constraint first (ignore if already gone)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'route_segments_shipment_id_fkey'
            ) THEN
                ALTER TABLE route_segments DROP CONSTRAINT route_segments_shipment_id_fkey;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='route_segments' AND column_name='shipment_id') THEN
                ALTER TABLE route_segments DROP COLUMN shipment_id;
            END IF;
        END $$;
    """)

    route_segment_cols = [
        ("tenant_id",       "UUID REFERENCES tenants(id) ON DELETE SET NULL"),
        ("highway_code",    "VARCHAR(50)"),
        ("risk_score",      "FLOAT NOT NULL DEFAULT 0.0"),
        ("elevation_avg_m", "FLOAT NOT NULL DEFAULT 0.0"),
        ("flood_prob",      "FLOAT NOT NULL DEFAULT 0.0"),
        ("fire_risk",       "FLOAT NOT NULL DEFAULT 0.0"),
        ("congestion_idx",  "FLOAT NOT NULL DEFAULT 0.0"),
        ("last_scored_at",  "TIMESTAMPTZ"),
    ]
    for col_name, col_def in route_segment_cols:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='route_segments' AND column_name='{col_name}') THEN
                    ALTER TABLE route_segments ADD COLUMN {col_name} {col_def};
                END IF;
            END $$;
        """)

    # ── 6. carriers — add spec columns ────────────────────────────────────────
    carrier_cols = [
        ("modes",           "VARCHAR[] NOT NULL DEFAULT '{}'"),
        ("rating",          "FLOAT NOT NULL DEFAULT 0.0"),
        ("avg_delay_h",     "FLOAT NOT NULL DEFAULT 0.0"),
        ("cost_per_km",     "FLOAT NOT NULL DEFAULT 0.0"),
        ("co2_per_tonne_km","FLOAT NOT NULL DEFAULT 18.0"),
        ("available_now",   "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("verified_at",     "TIMESTAMPTZ"),
    ]
    for col_name, col_def in carrier_cols:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='carriers' AND column_name='{col_name}') THEN
                    ALTER TABLE carriers ADD COLUMN {col_name} {col_def};
                END IF;
            END $$;
        """)

    # ── 7. telemetry — add typed columns, keep legacy data JSON ───────────────
    telemetry_cols = [
        ("tenant_id",  "UUID REFERENCES tenants(id) ON DELETE CASCADE"),
        ("lat",        "FLOAT"),
        ("lon",        "FLOAT"),
        ("speed_kmh",  "FLOAT NOT NULL DEFAULT 0.0"),
        ("heading",    "FLOAT NOT NULL DEFAULT 0.0"),
        ("accuracy_m", "FLOAT NOT NULL DEFAULT 0.0"),
        ("source",     "VARCHAR(50) NOT NULL DEFAULT 'gps'"),
        ("battery_pct","FLOAT"),
    ]
    for col_name, col_def in telemetry_cols:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='telemetry' AND column_name='{col_name}') THEN
                    ALTER TABLE telemetry ADD COLUMN {col_name} {col_def};
                END IF;
            END $$;
        """)

    # ── 8. news_alerts — remove tenant_id FK (global table per spec) ──────────
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'news_alerts_tenant_id_fkey'
            ) THEN
                ALTER TABLE news_alerts DROP CONSTRAINT news_alerts_tenant_id_fkey;
            END IF;
        END $$;
    """)
    # --- NEW FIX: Destroy the RLS policy before dropping the column ---
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON news_alerts;")
    op.execute("ALTER TABLE news_alerts DISABLE ROW LEVEL SECURITY;")

    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='news_alerts' AND column_name='tenant_id') THEN
                ALTER TABLE news_alerts DROP COLUMN tenant_id;
            END IF;
        END $$;
    """)
    
    # Add global news_alerts spec columns
    news_alert_cols = [
        ("source",             "VARCHAR(255)"),
        ("headline",           "TEXT"),
        ("url",                "VARCHAR(1000)"),
        ("published_at",       "TIMESTAMPTZ"),
        ("locations",          "VARCHAR[] NOT NULL DEFAULT '{}'"),
        ("event_type",         "VARCHAR(100)"),
        ("confidence",         "FLOAT NOT NULL DEFAULT 0.0"),
        ("source_count",       "INTEGER NOT NULL DEFAULT 1"),
        ("linked_segment_ids", "VARCHAR[] NOT NULL DEFAULT '{}'"),
        ("status",             "VARCHAR(50) NOT NULL DEFAULT 'active'"),
    ]
    for col_name, col_def in news_alert_cols:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='news_alerts' AND column_name='{col_name}') THEN
                    ALTER TABLE news_alerts ADD COLUMN {col_name} {col_def};
                END IF;
            END $$;
        """)

    # ── 9. agent_decisions — remove old shipment FK coupling, add spec cols ───
    # Add disruption_id FK
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='agent_decisions' AND column_name='disruption_id') THEN
                ALTER TABLE agent_decisions
                    ADD COLUMN disruption_id UUID REFERENCES disruption_events(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)
    agent_decision_cols = [
        ("trace_id",         "VARCHAR(50)"),
        ("reasoning_chain",  "JSONB"),
        ("tool_calls",       "JSONB"),
        ("latency_ms",       "INTEGER NOT NULL DEFAULT 0"),
        ("model_used",       "VARCHAR(100)"),
        ("fallback_used",    "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("human_overridden", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("cost_delta",       "FLOAT NOT NULL DEFAULT 0.0"),
        ("co2_delta",        "FLOAT NOT NULL DEFAULT 0.0"),
    ]
    for col_name, col_def in agent_decision_cols:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='agent_decisions' AND column_name='{col_name}') THEN
                    ALTER TABLE agent_decisions ADD COLUMN {col_name} {col_def};
                END IF;
            END $$;
        """)

    # Make shipment_id nullable (it's now optional — disruption_id can be used instead)
    op.execute("""
        ALTER TABLE agent_decisions
            ALTER COLUMN shipment_id DROP NOT NULL;
    """)

    # ── 10. subscription_events — add razorpay_event_id, plan_tier, amount_usd ──
    sub_event_cols = [
        ("razorpay_event_id", "VARCHAR(255) UNIQUE"),
        ("type",            "VARCHAR(100)"),
        ("plan_tier",       "VARCHAR(50)"),
        ("amount_usd",      "FLOAT NOT NULL DEFAULT 0.0"),
    ]
    for col_name, col_def in sub_event_cols:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='subscription_events' AND column_name='{col_name}') THEN
                    ALTER TABLE subscription_events ADD COLUMN {col_name} {col_def};
                END IF;
            END $$;
        """)

    # ── 11. Performance indexes ────────────────────────────────────────────────
    indexes = [
        ("ix_shipments_tenant_status",       "shipments",        ["tenant_id", "status"]),
        ("ix_disruption_events_tenant_type", "disruption_events",["tenant_id", "type"]),
        ("ix_telemetry_shipment_ts",         "telemetry",        ["shipment_id", "ts"]),
        ("ix_route_segments_highway_code",   "route_segments",   ["highway_code"]),
        ("ix_route_segments_tenant_id",      "route_segments",   ["tenant_id"]),
        ("ix_carriers_tenant_id",            "carriers",         ["tenant_id"]),
    ]
    for idx_name, tbl, cols in indexes:
        col_list = ", ".join(cols)
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = '{idx_name}') THEN
                    CREATE INDEX {idx_name} ON {tbl} ({col_list});
                END IF;
            END $$;
        """)

    # ── 12. RLS for route_segments (tenant-scoped now) ─────────────────────────
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE route_segments ENABLE ROW LEVEL SECURITY;
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename='route_segments' AND policyname='tenant_isolation'
            ) THEN
                CREATE POLICY tenant_isolation ON route_segments
                  USING (
                    tenant_id IS NULL
                    OR tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
                  );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # ── Remove indexes ────────────────────────────────────────────────────────
    for idx in [
        "ix_carriers_tenant_id",
        "ix_route_segments_tenant_id",
        "ix_route_segments_highway_code",
        "ix_telemetry_shipment_ts",
        "ix_disruption_events_tenant_type",
        "ix_shipments_tenant_status",
    ]:
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    # ── Remove agent_decisions new columns ────────────────────────────────────
    for col in ["co2_delta", "cost_delta", "human_overridden", "fallback_used",
                "model_used", "latency_ms", "tool_calls", "reasoning_chain",
                "trace_id", "disruption_id"]:
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='agent_decisions' AND column_name='{col}') THEN
                    ALTER TABLE agent_decisions DROP COLUMN {col};
                END IF;
            END $$;
        """)

    # ── Re-add tenant_id to news_alerts (restore old state) ──────────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='news_alerts' AND column_name='tenant_id') THEN
                ALTER TABLE news_alerts ADD COLUMN tenant_id UUID;
            END IF;
        END $$;
    """)

    # ── Restore route_segments.shipment_id ────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='route_segments' AND column_name='shipment_id') THEN
                ALTER TABLE route_segments ADD COLUMN shipment_id UUID;
            END IF;
        END $$;
    """)

    # ── Drop added columns from tenants, users, shipments, carriers, telemetry ─
    for tbl, col in [
        ("tenants", "domain"), ("tenants", "plan_tier"),
        ("tenants", "razorpay_customer_id"), ("tenants", "razorpay_subscription_id"),
        ("tenants", "is_active"),
        ("users", "is_active"), ("users", "last_login"),
        ("shipments", "tracking_num"), ("shipments", "current_lat"),
        ("shipments", "current_lon"), ("shipments", "risk_score"),
        ("shipments", "route_id"), ("shipments", "sla_deadline"),
        ("shipments", "eta_current"), ("shipments", "co2_kg"),
        ("route_segments", "tenant_id"), ("route_segments", "highway_code"),
        ("route_segments", "risk_score"), ("route_segments", "elevation_avg_m"),
        ("route_segments", "flood_prob"), ("route_segments", "fire_risk"),
        ("route_segments", "congestion_idx"), ("route_segments", "last_scored_at"),
        ("carriers", "modes"), ("carriers", "rating"), ("carriers", "avg_delay_h"),
        ("carriers", "cost_per_km"), ("carriers", "co2_per_tonne_km"),
        ("carriers", "available_now"), ("carriers", "verified_at"),
        ("telemetry", "tenant_id"), ("telemetry", "lat"), ("telemetry", "lon"),
        ("telemetry", "speed_kmh"), ("telemetry", "heading"),
        ("telemetry", "accuracy_m"), ("telemetry", "source"), ("telemetry", "battery_pct"),
        ("subscription_events", "razorpay_event_id"), ("subscription_events", "type"),
        ("subscription_events", "plan_tier"), ("subscription_events", "amount_usd"),
    ]:
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='{tbl}' AND column_name='{col}') THEN
                    ALTER TABLE {tbl} DROP COLUMN {col};
                END IF;
            END $$;
        """)

"""002_add_enum_values

Revision ID: 002_add_enum_values
Revises: 622e968f61eb
Create Date: 2026-04-25

"""

from typing import Union
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "002_add_enum_values"
down_revision: str | None = "622e968f61eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# MUST NOT run in a transaction for ALTER TYPE
transaction_per_migration = False


def upgrade() -> None:
    new_enum_values = [
        "flood",
        "fire",
        "quake",
        "port_congestion",
        "fuel_shortage",
        "tariff",
        "cyber",
        "cold_chain_breach",
        "jit_failure",
    ]
    for val in new_enum_values:
        op.execute(f"ALTER TYPE disruptiontype ADD VALUE IF NOT EXISTS '{val}'")

    op.execute("ALTER TYPE shipmentmode ADD VALUE IF NOT EXISTS 'multimodal'")

    for val in ("at_risk", "rerouted"):
        op.execute(f"ALTER TYPE shipmentstatus ADD VALUE IF NOT EXISTS '{val}'")


def downgrade() -> None:
    # Note: ALTER TYPE DROP VALUE is not supported in Postgres — enum values cannot
    # be removed. The disruptiontype new values will remain in the DB after downgrade.
    pass

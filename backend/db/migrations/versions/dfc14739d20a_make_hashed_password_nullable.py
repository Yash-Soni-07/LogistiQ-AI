"""make_hashed_password_nullable

Revision ID: dfc14739d20a
Revises: 730413e36e98
Create Date: 2026-05-03 13:39:31.887418+00:00

Purpose:
  Allow the hashed_password column to be NULL so that users who register
  via Google OAuth (and therefore have no password) can be stored without
  a dummy/placeholder value.

  Email/password users are unaffected — their hashed_password remains a
  non-null bcrypt hash as before.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = 'dfc14739d20a'
down_revision: Union[str, None] = '730413e36e98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make hashed_password nullable to support Google OAuth users
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.VARCHAR(),
        nullable=True,
    )


def downgrade() -> None:
    # Revert: hashed_password back to NOT NULL
    # WARNING: any rows with NULL hashed_password will cause this to fail.
    # Delete or update Google-OAuth-only users before running downgrade.
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.VARCHAR(),
        nullable=False,
    )

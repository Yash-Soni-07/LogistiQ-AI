"""db/migrations/env.py — Alembic runtime environment for LogistiQ AI.

Key decisions
─────────────
- Async engine: uses ``asyncpg`` driver via ``run_async_migrations()`` so Alembic
  works with the same async engine that the FastAPI app uses.
- DATABASE_URL is read from core.config.settings so the single .env file is the
  source of truth — no duplication with alembic.ini.
- include_schemas=True + include_object filter: prevents Alembic from touching
  PostGIS system tables (geometry_columns, spatial_ref_sys, etc.).
- RLS policies are created in individual migration scripts via op.execute();
  Alembic does not autogenerate them, so they are excluded from autogenerate diff.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Load app config + models ──────────────────────────────────
# Import settings before anything else so DATABASE_URL is available.
import sys
import os

# Allow imports from the backend package root when running `alembic` from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from core.config import settings  # noqa: E402
from db.models import Base  # noqa: E402  — imports all ORM models, populating metadata

# ── Alembic Config object ─────────────────────────────────────
config = context.config

# Override the sqlalchemy.url from alembic.ini with the real DATABASE_URL
# so we never need to keep two copies in sync.
config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL).replace("%", "%%"))

# Interpret the config file for Python logging setup
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MetaData object for 'autogenerate' support
target_metadata = Base.metadata


# ── Helper: filter autogenerate to skip PostGIS system objects ─

_POSTGIS_TABLES = frozenset(
    {
        "geometry_columns",
        "geography_columns",
        "spatial_ref_sys",
        "raster_columns",
        "raster_overviews",
    }
)

_POSTGIS_SCHEMAS = frozenset({"topology", "tiger", "tiger_data"})


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Tell Alembic autogenerate to skip PostGIS system tables and schemas."""
    if type_ == "schema" and name in _POSTGIS_SCHEMAS:
        return False
    if type_ == "table" and name in _POSTGIS_TABLES:
        return False
    return True


# ── Offline migrations ────────────────────────────────────────


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL script, no DB connection).

    Called by: ``alembic upgrade head --sql > migration.sql``
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (async) ─────────────────────────────────


def do_run_migrations(connection: Connection) -> None:
    """Run migrations synchronously on an existing connection (called from async context)."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
        # Render AS OWNER so PostGIS geometry DDL uses correct type representation
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # migrations never need a connection pool
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations — runs the async migration loop."""
    asyncio.run(run_async_migrations())


# ── Dispatch ──────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Alembic environment.

The URL comes from application settings, not from `alembic.ini`, so migrations and
the running app can never disagree about which database they mean. Override it for
one-off runs with `ALEMBIC_DATABASE_URL`.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import TYPE_CHECKING

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.shared.db.registry import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `app.shared.db.registry` is imported above so that every mapped class is
# attached to `Base.metadata`. Without it, autogenerate would not see the tables
# and would emit a migration that drops them.
target_metadata = Base.metadata


def _database_url() -> str:
    override = os.environ.get("ALEMBIC_DATABASE_URL")
    if override:
        return override
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Named constraints (see app.shared.db.base.NAMING_CONVENTION) are what
        # make future downgrades expressible.
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

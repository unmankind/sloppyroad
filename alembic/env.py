"""Alembic migration environment for async SQLAlchemy.

Imports all models from db/models.py so autogenerate can detect schema changes.
Uses async engine matching the application config.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Alembic Config object
config = context.config

# Set up logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models for autogeneration detection.
# BEDROCK will populate db/models.py with the canonical Base and all models.
try:
    from aiwebnovel.db.models import Base

    target_metadata = Base.metadata
except ImportError:
    # Models not yet created — allow alembic to initialize without them
    from sqlalchemy.orm import DeclarativeBase

    class _FallbackBase(DeclarativeBase):
        pass

    target_metadata = _FallbackBase.metadata


def get_url() -> str:
    """Get database URL from config or environment."""
    try:
        from aiwebnovel.config import Settings

        settings = Settings()
        return settings.database_url
    except Exception:
        return config.get_main_option("sqlalchemy.url", "sqlite+aiosqlite:///./aiwebnovel.db")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without connecting."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Run migrations against a live connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    url = get_url()
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations — delegates to async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

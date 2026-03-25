"""Database session management for AIWN 2.0.

Provides async engine factory, session factory, FastAPI dependency,
and a transaction context manager.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def get_engine(
    database_url: str,
    echo: bool = False,
    *,
    pool_size: int = 10,
    pool_max_overflow: int = 20,
    pool_recycle: int = 3600,
    pool_pre_ping: bool = True,
    **kwargs: Any,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Automatically adjusts connection arguments for SQLite vs PostgreSQL.
    Pool settings are applied only to non-SQLite databases.
    """
    connect_args: dict[str, Any] = {}

    if database_url.startswith("sqlite"):
        # SQLite requires check_same_thread=False for async usage
        connect_args["check_same_thread"] = False
        # Wait up to 30s for write locks instead of failing immediately
        connect_args["timeout"] = 30
    else:
        # Connection pool tuning for PostgreSQL / other server databases
        kwargs.setdefault("pool_size", pool_size)
        kwargs.setdefault("max_overflow", pool_max_overflow)
        kwargs.setdefault("pool_recycle", pool_recycle)
        kwargs.setdefault("pool_pre_ping", pool_pre_ping)

    engine = create_async_engine(
        database_url,
        echo=echo,
        connect_args=connect_args,
        **kwargs,
    )

    if database_url.startswith("sqlite"):
        # Enable WAL mode for better concurrency (allows reads during writes)
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: Any, _rec: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# ---------------------------------------------------------------------------
# Module-level state set by ``init_db`` during app startup
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str, echo: bool = False, **kwargs: Any) -> AsyncEngine:
    """Initialise the module-level engine and session factory.

    Called once during FastAPI lifespan startup.  Extra *kwargs* are
    forwarded to :func:`get_engine` (e.g. pool_size, pool_pre_ping).
    """
    global _engine, _session_factory  # noqa: PLW0603

    _engine = get_engine(database_url, echo=echo, **kwargs)
    _session_factory = get_session_factory(_engine)
    return _engine


async def close_db() -> None:
    """Dispose of the module-level engine.

    Called during FastAPI lifespan shutdown.
    """
    global _engine, _session_factory  # noqa: PLW0603

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async session.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    if _session_factory is None:
        msg = "Database not initialised. Call init_db() first."
        raise RuntimeError(msg)

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:  # Intentional broad catch: rollback on any error before re-raising
            await session.rollback()
            raise


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for explicit multi-step transactions.

    Usage::

        async with transaction(session) as txn:
            txn.add(obj_a)
            txn.add(obj_b)
            # commit happens automatically on clean exit
            # rollback happens on exception

    This wraps the session in a nested savepoint so the caller's
    outer session state is preserved on failure.
    """
    async with session.begin_nested():
        yield session

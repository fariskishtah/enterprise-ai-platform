"""SQLAlchemy async session factory helpers."""

from sqlalchemy import event
from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import Pool

from app.observability.metrics import record_database_pool_state


def build_engine(
    database_url: str,
    *,
    pool_size: int = 4,
    max_overflow: int = 2,
    pool_timeout_seconds: float = 5.0,
    pool_recycle_seconds: int = 1800,
) -> AsyncEngine:
    """Build an async SQLAlchemy engine."""
    # The module attribute is intentionally resolved at call time so the official
    # OpenTelemetry SQLAlchemy instrumentor can wrap async engine construction.
    engine = sqlalchemy_asyncio.create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout_seconds,
        pool_recycle=pool_recycle_seconds,
    )
    _instrument_pool(engine.sync_engine.pool)
    return engine


def build_session_factory(
    database_url: str,
    *,
    pool_size: int = 4,
    max_overflow: int = 2,
    pool_timeout_seconds: float = 5.0,
    pool_recycle_seconds: int = 1800,
) -> async_sessionmaker[AsyncSession]:
    """Build an async SQLAlchemy session factory."""
    engine = build_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout_seconds=pool_timeout_seconds,
        pool_recycle_seconds=pool_recycle_seconds,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def _instrument_pool(pool: Pool) -> None:
    """Publish bounded pool state after connection lifecycle changes."""

    def update_state(*_args: object) -> None:
        size = getattr(pool, "size", lambda: 0)()
        checked_in = getattr(pool, "checkedin", lambda: 0)()
        checked_out = getattr(pool, "checkedout", lambda: 0)()
        overflow = max(getattr(pool, "overflow", lambda: 0)(), 0)
        record_database_pool_state(
            size=size,
            checked_in=checked_in,
            checked_out=checked_out,
            overflow=overflow,
        )

    event.listen(pool, "connect", update_state)
    event.listen(pool, "checkout", update_state)
    event.listen(pool, "checkin", update_state)
    event.listen(pool, "close", update_state)

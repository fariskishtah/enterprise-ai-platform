"""Database dependencies."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings, get_settings
from app.db.session import build_session_factory
from app.observability.metrics import record_database_pool_exhaustion


@lru_cache
def get_session_factory(
    database_url: str,
    pool_size: int,
    max_overflow: int,
    pool_timeout_seconds: float,
    pool_recycle_seconds: int,
) -> async_sessionmaker[AsyncSession]:
    """Return a cached session factory for the configured database URL."""
    return build_session_factory(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout_seconds=pool_timeout_seconds,
        pool_recycle_seconds=pool_recycle_seconds,
    )


async def get_db_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session."""
    session_factory = get_session_factory(
        settings.database_url,
        settings.database_pool_size,
        settings.database_max_overflow,
        settings.database_pool_timeout_seconds,
        settings.database_pool_recycle_seconds,
    )
    async with session_factory() as session:
        try:
            yield session
        except SQLAlchemyTimeoutError:
            record_database_pool_exhaustion()
            raise

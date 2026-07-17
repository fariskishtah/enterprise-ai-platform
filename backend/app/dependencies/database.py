"""Database dependencies."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings, get_settings
from app.db.session import build_session_factory


@lru_cache
def get_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Return a cached session factory for the configured database URL."""
    return build_session_factory(database_url)


async def get_db_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session."""
    session_factory = get_session_factory(settings.database_url)
    async with session_factory() as session:
        yield session

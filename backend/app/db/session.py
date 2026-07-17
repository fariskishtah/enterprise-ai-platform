"""SQLAlchemy async session factory helpers."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(database_url: str) -> AsyncEngine:
    """Build an async SQLAlchemy engine."""
    return create_async_engine(database_url, pool_pre_ping=True)


def build_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Build an async SQLAlchemy session factory."""
    engine = build_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)

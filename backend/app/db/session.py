"""SQLAlchemy async session factory helpers."""

from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def build_engine(database_url: str) -> AsyncEngine:
    """Build an async SQLAlchemy engine."""
    # The module attribute is intentionally resolved at call time so the official
    # OpenTelemetry SQLAlchemy instrumentor can wrap async engine construction.
    return sqlalchemy_asyncio.create_async_engine(database_url, pool_pre_ping=True)


def build_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Build an async SQLAlchemy session factory."""
    engine = build_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)

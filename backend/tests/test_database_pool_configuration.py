"""Explicit SQLAlchemy pool configuration and instrumentation contracts."""

from types import SimpleNamespace
from typing import cast

import pytest
from app.db import session as session_module
from sqlalchemy.ext.asyncio import AsyncEngine


def test_build_engine_applies_bounded_pool_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = object()
    engine = SimpleNamespace(sync_engine=SimpleNamespace(pool=pool))
    calls: list[dict[str, object]] = []
    events: list[str] = []
    monkeypatch.setattr(
        session_module.sqlalchemy_asyncio,
        "create_async_engine",
        lambda _url, **kwargs: calls.append(kwargs) or engine,
    )
    monkeypatch.setattr(
        session_module.event,
        "listen",
        lambda target, name, _callback: events.append(name) if target is pool else None,
    )

    result = session_module.build_engine(
        "postgresql+psycopg://example.invalid/db",
        pool_size=10,
        max_overflow=5,
        pool_timeout_seconds=5.0,
        pool_recycle_seconds=1800,
    )

    assert result is cast(AsyncEngine, engine)
    assert calls == [
        {
            "pool_pre_ping": True,
            "pool_size": 10,
            "max_overflow": 5,
            "pool_timeout": 5.0,
            "pool_recycle": 1800,
        }
    ]
    assert events == ["connect", "checkout", "checkin", "close"]

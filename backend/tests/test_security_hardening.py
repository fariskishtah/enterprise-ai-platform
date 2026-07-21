"""Focused API-boundary security hardening tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.config.settings import Settings
from app.core.application import create_app
from app.dependencies.database import get_db_session
from app.dependencies.rate_limit import get_auth_rate_limit_store
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class MemoryRateLimitStore:
    """Deterministic store for exercising the real endpoint dependency."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key], min(window_seconds, 37)


def _validated_settings(settings: Settings, **updates: object) -> Settings:
    values = settings.model_dump()
    values.update(updates)
    return Settings.model_validate(values)


@pytest.mark.anyio
async def test_security_headers_cover_api_and_preserve_docs(
    api_client: AsyncClient,
) -> None:
    """API responses are hardened while development Swagger remains CSP-compatible."""
    health = await api_client.get("/health")
    docs = await api_client.get("/docs")
    auth_failure = await api_client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "not-the-password"},
    )

    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"
    assert health.headers["Referrer-Policy"] == "no-referrer"
    assert health.headers["Permissions-Policy"] == (
        "camera=(), geolocation=(), microphone=()"
    )
    assert health.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    )
    assert docs.status_code == 200
    assert "Content-Security-Policy" not in docs.headers
    assert auth_failure.headers["Cache-Control"] == "no-store"


@pytest.mark.anyio
async def test_api_documentation_routes_follow_explicit_setting(
    settings: Settings,
) -> None:
    """Docs, ReDoc, and the schema are either all exposed or all absent."""
    enabled = create_app(_validated_settings(settings, enable_api_docs=True))
    disabled = create_app(_validated_settings(settings, enable_api_docs=False))

    async with AsyncClient(
        transport=ASGITransport(app=enabled), base_url="http://testserver"
    ) as client:
        assert (await client.get("/docs")).status_code == 200
        assert (await client.get("/redoc")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200

    async with AsyncClient(
        transport=ASGITransport(app=disabled), base_url="http://testserver"
    ) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/redoc")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404


@pytest.mark.anyio
async def test_cors_allows_configured_local_origin_only(
    api_client: AsyncClient,
) -> None:
    """CORS preflights accept the explicit allowlist and reject arbitrary origins."""
    preflight_headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Authorization,Content-Type",
    }
    allowed = await api_client.options(
        "/auth/login",
        headers={"Origin": "http://localhost:5173", **preflight_headers},
    )
    rejected = await api_client.options(
        "/auth/login",
        headers={"Origin": "https://attacker.example", **preflight_headers},
    )

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert rejected.status_code == 400
    assert "Access-Control-Allow-Origin" not in rejected.headers


@pytest.mark.anyio
async def test_sensitive_auth_routes_are_rate_limited_with_bounded_retry_after(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Registration, login, and refresh each enforce the narrow Redis boundary."""
    limited_settings = _validated_settings(
        settings,
        auth_rate_limit_enabled=True,
        auth_rate_limit_requests=1,
        auth_rate_limit_window_seconds=60,
    )
    application = create_app(limited_settings)
    store = MemoryRateLimitStore()

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_get_db_session
    application.dependency_overrides[get_auth_rate_limit_store] = lambda: store
    transport = ASGITransport(app=application)
    requests = (
        ("/auth/register", {"email": "invalid", "password": "short"}),
        (
            "/auth/login",
            {"email": "unknown@example.com", "password": "not-the-password"},
        ),
        ("/auth/refresh", {"refresh_token": "not-a-token"}),
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for path, payload in requests:
            first = await client.post(path, json=payload)
            limited = await client.post(path, json=payload)

            assert first.status_code in {401, 422}
            assert limited.status_code == 429
            assert limited.json()["detail"] == "Too many authentication attempts."
            assert limited.headers["Retry-After"] == "37"
            assert 1 <= int(limited.headers["Retry-After"]) <= 3600


def test_production_disables_debug_and_local_cors(settings: Settings) -> None:
    """Production has no debug docs and rejects development-only CORS origins."""
    production = _validated_settings(
        settings,
        environment="production",
        enable_api_docs=False,
        cors_allowed_origins=(),
    )
    application = create_app(production)

    assert application.debug is False
    assert application.docs_url is None
    assert application.redoc_url is None
    assert application.openapi_url is None
    with pytest.raises(ValidationError):
        _validated_settings(settings, environment="production")


def test_production_rejects_enabled_api_documentation(settings: Settings) -> None:
    """Production cannot accidentally expose documentation routes."""
    with pytest.raises(ValidationError, match="enable_api_docs must be false"):
        _validated_settings(
            settings,
            environment="production",
            enable_api_docs=True,
            cors_allowed_origins=("https://platform.example",),
        )


def test_cors_rejects_wildcard_origin(settings: Settings) -> None:
    """An arbitrary wildcard cannot enter the CORS allowlist."""
    with pytest.raises(ValidationError):
        _validated_settings(settings, cors_allowed_origins=("*",))

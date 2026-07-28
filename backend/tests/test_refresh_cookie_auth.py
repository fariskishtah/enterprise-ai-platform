"""Security coverage for the refresh-cookie browser contract."""

from datetime import timedelta

import pytest
from app.config.settings import Settings
from app.models.user import RefreshToken
from app.security.cookie_auth import issue_auth_cookies
from app.utils.security import utc_now
from fastapi import Response
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_auth_api import VALID_PASSWORD, login_user, register_user

REFRESH_COOKIE = "factorymind_refresh"
CSRF_COOKIE = "factorymind_csrf"


def _csrf(client: AsyncClient) -> dict[str, str]:
    value = client.cookies.get(CSRF_COOKIE)
    assert value is not None
    return {"X-CSRF-Token": value}


@pytest.mark.anyio
async def test_login_cookie_attributes_and_no_refresh_token_exposure(
    api_client: AsyncClient,
) -> None:
    await register_user(api_client)
    response = await api_client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": VALID_PASSWORD},
    )
    cookies = response.headers.get_list("set-cookie")
    refresh = next(item for item in cookies if item.startswith(f"{REFRESH_COOKIE}="))
    csrf = next(item for item in cookies if item.startswith(f"{CSRF_COOKIE}="))

    assert response.status_code == 200
    assert "refresh_token" not in response.json()
    assert "HttpOnly" in refresh
    assert "HttpOnly" not in csrf
    assert "Path=/auth" in refresh
    assert "SameSite=lax" in refresh
    assert "Max-Age=2592000" in refresh


def test_production_cookie_configuration_emits_secure_scoped_flags(
    settings: Settings,
) -> None:
    production_cookie_settings = settings.model_copy(
        update={
            "cookie_domain": "platform.example",
            "cookie_samesite": "strict",
            "cookie_secure": True,
        }
    )
    response = Response()
    issue_auth_cookies(
        response,
        refresh_token="server-only-refresh-token",
        settings=production_cookie_settings,
    )
    cookies = response.headers.getlist("set-cookie")
    refresh = next(item for item in cookies if item.startswith(f"{REFRESH_COOKIE}="))

    assert "HttpOnly" in refresh
    assert "Secure" in refresh
    assert "SameSite=strict" in refresh
    assert "Domain=platform.example" in refresh
    assert "Path=/auth" in refresh


@pytest.mark.anyio
async def test_refresh_requires_matching_csrf_and_allowed_origin(
    api_client: AsyncClient,
) -> None:
    await register_user(api_client)
    await login_user(api_client)

    missing = await api_client.post("/auth/refresh")
    mismatch = await api_client.post(
        "/auth/refresh", headers={"X-CSRF-Token": "incorrect"}
    )
    foreign = await api_client.post(
        "/auth/refresh",
        headers={**_csrf(api_client), "Origin": "https://attacker.example"},
    )
    allowed = await api_client.post(
        "/auth/refresh",
        headers={**_csrf(api_client), "Origin": "http://localhost:5173"},
    )

    assert missing.status_code == 403
    assert mismatch.status_code == 403
    assert foreign.status_code == 403
    assert allowed.status_code == 200


@pytest.mark.anyio
async def test_expired_and_explicitly_revoked_sessions_cannot_refresh(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_user(api_client)
    tokens = await login_user(api_client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    sessions = await api_client.get("/users/me/sessions", headers=headers)
    session_id = sessions.json()["items"][0]["id"]
    revoked = await api_client.delete(
        f"/users/me/sessions/{session_id}", headers=headers
    )
    rejected = await api_client.post("/auth/refresh", headers=_csrf(api_client))
    assert revoked.status_code == 204
    assert rejected.status_code == 401

    await login_user(api_client)
    async with session_factory() as session:
        current = (
            (
                await session.execute(
                    select(RefreshToken)
                    .where(RefreshToken.revoked_at.is_(None))
                    .order_by(RefreshToken.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert current is not None
        current.expires_at = utc_now() - timedelta(seconds=1)
        await session.commit()
    expired = await api_client.post("/auth/refresh", headers=_csrf(api_client))
    assert expired.status_code == 401

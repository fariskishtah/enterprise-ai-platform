"""Authentication API tests."""

import pytest
from httpx import AsyncClient

VALID_PASSWORD = "ValidPassword1!"


async def register_user(
    api_client: AsyncClient,
    *,
    email: str = "user@example.com",
    password: str = VALID_PASSWORD,
) -> dict[str, object]:
    """Register a user through the public API."""
    response = await api_client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return response.json()


async def login_user(
    api_client: AsyncClient,
    *,
    email: str = "user@example.com",
    password: str = VALID_PASSWORD,
) -> dict[str, object]:
    """Login through the public API."""
    response = await api_client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.anyio
async def test_register_creates_operator_user(api_client: AsyncClient) -> None:
    """Registration creates a user with the default operator role."""
    payload = await register_user(api_client, email="USER@Example.com")

    assert payload["email"] == "user@example.com"
    assert payload["role"] == "operator"
    assert payload["is_active"] is True
    assert "hashed_password" not in payload


@pytest.mark.anyio
async def test_register_rejects_duplicate_email(api_client: AsyncClient) -> None:
    """Registration enforces unique normalized email addresses."""
    await register_user(api_client, email="user@example.com")

    response = await api_client.post(
        "/auth/register",
        json={"email": "USER@example.com", "password": VALID_PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Email is already registered."


@pytest.mark.anyio
async def test_register_rejects_invalid_email(api_client: AsyncClient) -> None:
    """Registration validates email addresses."""
    response = await api_client.post(
        "/auth/register",
        json={"email": "invalid-email", "password": VALID_PASSWORD},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_register_rejects_weak_password(api_client: AsyncClient) -> None:
    """Registration enforces the password strength policy."""
    response = await api_client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "weak"},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_login_issues_token_pair(api_client: AsyncClient) -> None:
    """Login returns access and refresh tokens."""
    await register_user(api_client)

    payload = await login_user(api_client)

    assert isinstance(payload["access_token"], str)
    assert isinstance(payload["refresh_token"], str)
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == 900


@pytest.mark.anyio
async def test_login_rejects_invalid_password(api_client: AsyncClient) -> None:
    """Login rejects invalid credentials."""
    await register_user(api_client)

    response = await api_client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_refresh_rotates_refresh_token(api_client: AsyncClient) -> None:
    """Refresh rotates stored refresh tokens and rejects reuse."""
    await register_user(api_client)
    tokens = await login_user(api_client)
    refresh_token = str(tokens["refresh_token"])

    refresh_response = await api_client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    reuse_response = await api_client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 200
    assert refresh_response.json()["refresh_token"] != refresh_token
    assert reuse_response.status_code == 401


@pytest.mark.anyio
async def test_logout_revokes_refresh_token(api_client: AsyncClient) -> None:
    """Logout revokes a refresh token."""
    await register_user(api_client)
    tokens = await login_user(api_client)
    refresh_token = str(tokens["refresh_token"])

    logout_response = await api_client.post(
        "/auth/logout",
        json={"refresh_token": refresh_token},
    )
    refresh_response = await api_client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert logout_response.status_code == 204
    assert refresh_response.status_code == 401


@pytest.mark.anyio
async def test_users_me_returns_authenticated_user(api_client: AsyncClient) -> None:
    """The current-user endpoint returns the authenticated user."""
    await register_user(api_client)
    tokens = await login_user(api_client)

    response = await api_client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


@pytest.mark.anyio
async def test_users_me_requires_access_token(api_client: AsyncClient) -> None:
    """The current-user endpoint requires authentication."""
    response = await api_client.get("/users/me")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_openapi_documents_authentication_routes(
    api_client: AsyncClient,
) -> None:
    """OpenAPI exposes Sprint 2 authentication routes and bearer auth."""
    response = await api_client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/auth/register" in schema["paths"]
    assert "/auth/login" in schema["paths"]
    assert "/auth/refresh" in schema["paths"]
    assert "/auth/logout" in schema["paths"]
    assert "/users/me" in schema["paths"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]

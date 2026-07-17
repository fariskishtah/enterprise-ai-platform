"""Health-check endpoint tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health_check_returns_ok(api_client: AsyncClient) -> None:
    """The health endpoint reports a healthy backend service."""
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

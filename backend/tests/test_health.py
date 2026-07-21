"""Health-check endpoint tests."""

import pytest
from app.api.routes.health import readiness
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.anyio
async def test_health_check_returns_ok(api_client: AsyncClient) -> None:
    """The health endpoint reports a healthy backend service."""
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readiness_checks_primary_database(api_client: AsyncClient) -> None:
    """Readiness succeeds when the configured primary database answers."""
    response = await api_client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.anyio
async def test_readiness_sanitizes_database_failure() -> None:
    """Dependency failures produce a safe unavailable response."""

    class FailingSession:
        async def execute(self, _statement: object) -> None:
            raise SQLAlchemyError("internal database detail")

    with pytest.raises(HTTPException) as captured:
        await readiness(FailingSession())  # type: ignore[arg-type]

    assert captured.value.status_code == 503
    assert captured.value.detail == "A required service is unavailable."
    assert "internal database detail" not in str(captured.value.detail)

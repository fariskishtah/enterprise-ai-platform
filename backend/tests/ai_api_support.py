"""Shared isolated application and authentication helpers for AI API tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.config.settings import Settings
from app.core.application import create_app
from app.dependencies.database import get_db_session
from app.models.user import UserRole
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VALID_PASSWORD = "ValidPassword1!"


@asynccontextmanager
async def ai_api_client(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, FastAPI]]:
    """Return an API client with isolated database, MLflow, and artifact paths."""
    application = create_app(
        settings.model_copy(
            update={
                "mlflow_tracking_uri": f"file:{tmp_path / 'mlruns'}",
                "model_artifact_root": str(tmp_path / "mlflow-artifacts"),
                "ai_artifact_root": str(tmp_path / "ai-artifacts"),
            },
        ),
    )

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, application
    application.dependency_overrides.clear()


async def auth_headers(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    role: UserRole,
    email: str,
) -> dict[str, str]:
    """Create a role-specific user and return authenticated request headers."""
    async with session_factory() as session:
        service = UserService(
            repository=UserRepository(session),
            password_hasher=PasswordHasher(),
        )
        await service.create_user(email=email, password=VALID_PASSWORD, role=role)

    response = await client.post(
        "/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def regression_training_payload() -> dict[str, object]:
    """Return a small valid regression training request payload."""
    return {
        "training_features": [[0.0], [1.0], [2.0], [3.0]],
        "training_targets": [0.0, 1.0, 2.0, 3.0],
        "evaluation_features": [[0.5], [2.5]],
        "evaluation_targets": [0.5, 2.5],
        "hyperparameters": {"n_estimators": 3, "n_jobs": 1},
        "random_seed": 11,
        "experiment_name": "AI API Regression",
        "run_name": "regression-test",
        "tags": {"purpose": "api-test"},
    }


def classification_training_payload() -> dict[str, object]:
    """Return a small valid integer-label classification request payload."""
    return {
        "training_features": [[0.0], [0.5], [2.5], [3.0]],
        "training_targets": [0, 0, 1, 1],
        "evaluation_features": [[0.25], [2.75]],
        "evaluation_targets": [0, 1],
        "hyperparameters": {"n_estimators": 3, "n_jobs": 1},
        "random_seed": 13,
        "experiment_name": "AI API Classification",
        "run_name": "classification-test",
        "tags": {"purpose": "api-test"},
    }

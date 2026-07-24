"""MLOps API tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from app.config.settings import Settings
from app.core.application import create_app
from app.dependencies.database import get_db_session
from app.models.manufacturing import Company
from app.models.user import UserRole
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VALID_PASSWORD = "ValidPassword1!"


@asynccontextmanager
async def mlops_api_client(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tmp_path: Path,
) -> AsyncIterator[AsyncClient]:
    """Return an API client with isolated MLflow and artifact paths."""
    application = create_app(
        settings.model_copy(
            update={
                "mlflow_tracking_uri": f"file:{tmp_path / 'mlruns'}",
                "model_artifact_root": str(tmp_path / "artifacts"),
            },
        ),
    )

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    application.dependency_overrides.clear()


async def create_role_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
    role: UserRole,
) -> None:
    """Create a user for RBAC tests."""
    async with session_factory() as session:
        service = UserService(
            repository=UserRepository(session),
            password_hasher=PasswordHasher(),
        )
        company_id = await session.scalar(select(Company.id).limit(1))
        await service.create_user(
            email=email, password=VALID_PASSWORD, role=role, company_id=company_id
        )


async def auth_headers(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    role: UserRole,
    email: str,
) -> dict[str, str]:
    """Return Authorization headers for a user role."""
    await create_role_user(session_factory, email=email, role=role)
    response = await client.post(
        "/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_experiment_and_run(
    client: AsyncClient,
    headers: dict[str, str],
) -> tuple[dict[str, object], dict[str, object]]:
    """Create an experiment and training run through the API."""
    experiment_response = await client.post(
        "/experiments",
        headers=headers,
        json={
            "name": f"API Experiment {uuid4()}",
            "description": "API test experiment",
        },
    )
    assert experiment_response.status_code == 201
    experiment = experiment_response.json()

    run_response = await client.post(
        f"/experiments/{experiment['id']}/training-runs",
        headers=headers,
        json={
            "dataset_version": "dataset_v1",
            "algorithm": "baseline-regressor",
            "parameters": {"rolling_window": 5, "features": ["mean", "lag_1"]},
            "metrics": {"rmse": 1.25},
            "status": "PENDING",
        },
    )
    assert run_response.status_code == 201
    return experiment, run_response.json()


@pytest.mark.anyio
async def test_admin_can_create_experiment_run_and_artifact(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Admins can manage MLOps metadata through the API."""
    async with mlops_api_client(settings, session_factory, tmp_path=tmp_path) as client:
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="admin@example.com",
        )
        experiment, training_run = await create_experiment_and_run(client, headers)
        artifact_response = await client.post(
            f"/training-runs/{training_run['id']}/model-artifacts",
            headers=headers,
            json={
                "framework": "sklearn",
                "model_type": "metadata-only",
                "version": "v1",
                "artifact_path": "s3://models/api/v1/model.pkl",
                "checksum": "a" * 64,
            },
        )
        list_runs_response = await client.get(
            "/training-runs",
            headers=headers,
            params={"experiment_id": experiment["id"]},
        )
        list_artifacts_response = await client.get(
            "/model-artifacts",
            headers=headers,
            params={"training_run_id": training_run["id"]},
        )

    assert artifact_response.status_code == 201
    assert artifact_response.json()["training_run_id"] == training_run["id"]
    assert list_runs_response.status_code == 200
    assert list_runs_response.json()["total"] == 1
    assert list_artifacts_response.json()["items"][0]["version"] == "v1"


@pytest.mark.anyio
async def test_engineer_can_create_and_operator_is_read_only(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Engineers can create MLOps metadata and operators can only read."""
    async with mlops_api_client(settings, session_factory, tmp_path=tmp_path) as client:
        engineer_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="engineer@example.com",
        )
        operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="operator@example.com",
        )
        create_response = await client.post(
            "/experiments",
            headers=engineer_headers,
            json={"name": f"Engineer Experiment {uuid4()}"},
        )
        operator_list_response = await client.get(
            "/experiments",
            headers=operator_headers,
        )
        operator_create_response = await client.post(
            "/experiments",
            headers=operator_headers,
            json={"name": "Operator Experiment"},
        )

    assert create_response.status_code == 201
    assert operator_list_response.status_code == 200
    assert operator_create_response.status_code == 403


@pytest.mark.anyio
async def test_mlops_api_validation_errors(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """MLOps API returns proper validation and conflict responses."""
    async with mlops_api_client(settings, session_factory, tmp_path=tmp_path) as client:
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="admin@example.com",
        )
        duplicate_payload = {"name": "Duplicate Experiment"}
        first_response = await client.post(
            "/experiments",
            headers=headers,
            json=duplicate_payload,
        )
        duplicate_response = await client.post(
            "/experiments",
            headers=headers,
            json=duplicate_payload,
        )
        missing_experiment_response = await client.post(
            f"/experiments/{uuid4()}/training-runs",
            headers=headers,
            json={
                "dataset_version": "dataset_v1",
                "algorithm": "baseline-regressor",
                "parameters": {},
                "metrics": {},
            },
        )
        _, training_run = await create_experiment_and_run(client, headers)
        invalid_checksum_response = await client.post(
            f"/training-runs/{training_run['id']}/model-artifacts",
            headers=headers,
            json={
                "framework": "sklearn",
                "model_type": "metadata-only",
                "version": "v1",
                "artifact_path": "s3://models/api/invalid/model.pkl",
                "checksum": "not-a-sha256",
            },
        )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert missing_experiment_response.status_code == 422
    assert invalid_checksum_response.status_code == 422

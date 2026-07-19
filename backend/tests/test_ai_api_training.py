"""Authenticated synchronous Random Forest training API tests."""

from pathlib import Path

import pytest
from app.config.settings import Settings
from app.dependencies.services import (
    get_ai_experiment_tracker,
    get_ai_model_registry,
)
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationError,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
)
from app.ml.tracking import (
    BaseExperimentTracker,
    ExperimentRunInfo,
    ExperimentRunRequest,
    ExperimentTrackingError,
)
from app.models.user import UserRole
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import (
    ai_api_client,
    auth_headers,
    classification_training_payload,
    regression_training_payload,
)


class FailingExperimentTracker(BaseExperimentTracker):
    """Tracking adapter double that always reports an integration failure."""

    def log_successful_run(
        self,
        request: ExperimentRunRequest,
    ) -> ExperimentRunInfo:
        _ = request
        raise ExperimentTrackingError("tracking service unavailable")


class FailingModelRegistry(BaseModelRegistry):
    """Registry adapter double that fails after successful tracking."""

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        _ = request
        raise ModelRegistrationError("model registry unavailable")

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        _ = (registered_model_name, version_or_alias)
        raise RegisteredModelVersionNotFoundError("not used")


@pytest.mark.anyio
async def test_engineer_trains_and_registers_random_forest_regression(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Regression training returns safe local, tracking, and registry metadata."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="ai-regression@example.com",
        )
        response = await client.post(
            "/ai/training/random-forest/regression",
            headers=headers,
            json=regression_training_payload(),
        )

    body = response.json()
    assert response.status_code == 201
    assert body["trainer_key"] == {
        "algorithm": "random_forest",
        "task_type": "regression",
    }
    assert set(body["metrics"]) == {"mae", "mse", "rmse", "r2"}
    assert "local_artifact_path" not in body
    assert body["registered_model_name"] == "ai_core_random_forest_regression"
    assert body["registered_model_version"] == "1"
    assert body["mlflow_artifact_uri"].endswith("/model/model.joblib")
    assert body["duration_seconds"] >= 0


@pytest.mark.anyio
async def test_admin_trains_and_registers_random_forest_classification(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Classification training exposes typed integer-label metric metadata."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="ai-classification@example.com",
        )
        response = await client.post(
            "/ai/training/random-forest/classification",
            headers=headers,
            json=classification_training_payload(),
        )

    body = response.json()
    assert response.status_code == 201
    assert body["trainer_key"]["task_type"] == "classification"
    assert set(body["metrics"]) == {
        "accuracy",
        "precision_macro",
        "recall_macro",
        "f1_macro",
    }
    assert body["registered_model_name"] == ("ai_core_random_forest_classification")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("training_features", [[0.0], [1.0, 2.0]]),
        ("training_features", [[False], [1.0]]),
        ("training_targets", [0.0]),
        ("hyperparameters", {"n_estimators": 0}),
    ],
)
async def test_training_transport_rejects_invalid_arrays_and_parameters(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    """Ragged, boolean, mismatched, and invalid parameter inputs return 422."""
    payload = regression_training_payload()
    payload[field] = invalid_value
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email=f"invalid-{field}@example.com",
        )
        response = await client.post(
            "/ai/training/random-forest/regression",
            headers=headers,
            json=payload,
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_training_requires_engineer_or_admin_role(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Operators and unauthenticated callers cannot start model training."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="ai-operator@example.com",
        )
        operator_response = await client.post(
            "/ai/training/random-forest/regression",
            headers=operator_headers,
            json=regression_training_payload(),
        )
        unauthenticated_response = await client.post(
            "/ai/training/random-forest/regression",
            json=regression_training_payload(),
        )

    assert operator_response.status_code == 403
    assert unauthenticated_response.status_code == 401


@pytest.mark.anyio
async def test_training_translates_tracking_failure_to_bad_gateway(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Known external tracking failures return a sanitized 502 response."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_ai_experiment_tracker] = (
            FailingExperimentTracker
        )
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="ai-tracking-error@example.com",
        )
        response = await client.post(
            "/ai/training/random-forest/regression",
            headers=headers,
            json=regression_training_payload(),
        )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == "An external model service operation failed."
    assert "tracking service unavailable" not in detail
    assert len(tuple((tmp_path / "ai-artifacts").rglob("model.joblib"))) == 1


@pytest.mark.anyio
async def test_training_translates_registry_failure_to_bad_gateway(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Known registry failures return 502 after preserving completed tracking."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_ai_model_registry] = FailingModelRegistry
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="ai-registry-error@example.com",
        )
        response = await client.post(
            "/ai/training/random-forest/regression",
            headers=headers,
            json=regression_training_payload(),
        )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == "An external model service operation failed."
    assert "model registry unavailable" not in detail

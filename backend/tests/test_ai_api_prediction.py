"""Authenticated registered Random Forest prediction API tests."""

from pathlib import Path

import pytest
from app.config.settings import Settings
from app.dependencies.services import (
    get_ai_model_registry,
    get_ai_registered_model_loader,
)
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    ModelRegistryError,
    RegisteredModelVersion,
)
from app.ml.services import BaseRegisteredModelLoader, RegisteredModelLoadError
from app.models.user import UserRole
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import (
    ai_api_client,
    auth_headers,
    classification_training_payload,
    regression_training_payload,
)


class FailingPredictionRegistry(BaseModelRegistry):
    """Registry double for external resolution failures."""

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        _ = request
        raise AssertionError("Prediction must not register a model.")

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        _ = (registered_model_name, version_or_alias)
        raise ModelRegistryError("registry resolution unavailable")


class FailingModelLoader(BaseRegisteredModelLoader):
    """Loader double for external artifact download failures."""

    def load[
        ModelT
    ](
        self,
        model_version: RegisteredModelVersion,
        expected_type: type[ModelT],
    ) -> ModelT:
        _ = (model_version, expected_type)
        raise RegisteredModelLoadError("registered artifact unavailable")


async def _train(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    classification: bool = False,
) -> dict[str, object]:
    path = (
        "/ai/training/random-forest/classification"
        if classification
        else "/ai/training/random-forest/regression"
    )
    payload = (
        classification_training_payload()
        if classification
        else regression_training_payload()
    )
    response = await client.post(path, headers=headers, json=payload)
    assert response.status_code == 201
    body: dict[str, object] = response.json()
    return body


@pytest.mark.anyio
async def test_regression_prediction_and_model_version_lookup(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """An authenticated operator predicts and resolves exact model metadata."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="ai-predict-regression@example.com",
        )
        training = await _train(client, headers=headers)
        model_name = str(training["registered_model_name"])
        model_version = str(training["registered_model_version"])
        prediction = await client.post(
            "/ai/predictions/random-forest/regression",
            headers=headers,
            json={
                "registered_model_name": model_name,
                "version_or_alias": model_version,
                "features": [[0.25], [2.75]],
            },
        )
        resolved = await client.get(
            f"/ai/models/{model_name}/versions/{model_version}",
            headers=headers,
        )

    assert prediction.status_code == 200
    assert prediction.json()["trainer_key"]["task_type"] == "regression"
    assert len(prediction.json()["predictions"]) == 2
    assert all(isinstance(value, float) for value in prediction.json()["predictions"])
    assert resolved.status_code == 200
    assert resolved.json()["model_version"] == model_version
    assert resolved.json()["status"] == "READY"


@pytest.mark.anyio
async def test_classification_prediction_returns_integer_labels(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Classification inference returns only integer class labels."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="ai-predict-classification@example.com",
        )
        engineer_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="ai-train-classification@example.com",
        )
        training = await _train(
            client,
            headers=engineer_headers,
            classification=True,
        )
        response = await client.post(
            "/ai/predictions/random-forest/classification",
            headers=headers,
            json={
                "registered_model_name": training["registered_model_name"],
                "version_or_alias": training["registered_model_version"],
                "features": [[0.25], [2.75]],
            },
        )

    assert response.status_code == 200
    assert response.json()["predictions"] == [0, 1]
    assert all(isinstance(value, int) for value in response.json()["predictions"])


@pytest.mark.anyio
async def test_prediction_rejects_invalid_missing_and_wrong_task_models(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Transport, lookup, and task/model conflicts map to 422, 404, and 409."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="ai-prediction-errors@example.com",
        )
        training = await _train(client, headers=headers)
        model_name = str(training["registered_model_name"])
        model_version = str(training["registered_model_version"])
        invalid = await client.post(
            "/ai/predictions/random-forest/regression",
            headers=headers,
            json={
                "registered_model_name": model_name,
                "version_or_alias": model_version,
                "features": [[0.0], [1.0, 2.0]],
            },
        )
        missing = await client.post(
            "/ai/predictions/random-forest/regression",
            headers=headers,
            json={
                "registered_model_name": "ai_core_missing_regression",
                "version_or_alias": "1",
                "features": [[0.0]],
            },
        )
        wrong_task = await client.post(
            "/ai/predictions/random-forest/classification",
            headers=headers,
            json={
                "registered_model_name": model_name,
                "version_or_alias": model_version,
                "features": [[0.0]],
            },
        )

    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert wrong_task.status_code == 409


@pytest.mark.anyio
async def test_prediction_requires_authentication(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Registered model inference follows the authenticated-user convention."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        response = await client.post(
            "/ai/predictions/random-forest/regression",
            json={
                "registered_model_name": "ai_core_random_forest_regression",
                "version_or_alias": "1",
                "features": [[0.0]],
            },
        )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_prediction_translates_registry_failure_to_bad_gateway(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Known external registry failures return a sanitized 502 response."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_ai_model_registry] = (
            FailingPredictionRegistry
        )
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="ai-prediction-registry-error@example.com",
        )
        response = await client.post(
            "/ai/predictions/random-forest/regression",
            headers=headers,
            json={
                "registered_model_name": "ai_core_random_forest_regression",
                "version_or_alias": "1",
                "features": [[0.0]],
            },
        )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == "An external model service operation failed."
    assert "registry resolution unavailable" not in detail


@pytest.mark.anyio
async def test_prediction_translates_model_loading_failure_to_bad_gateway(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Known registered-artifact load failures return a sanitized 502 response."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="ai-prediction-loader-error@example.com",
        )
        training = await _train(client, headers=headers)
        application.dependency_overrides[get_ai_registered_model_loader] = (
            FailingModelLoader
        )
        response = await client.post(
            "/ai/predictions/random-forest/regression",
            headers=headers,
            json={
                "registered_model_name": training["registered_model_name"],
                "version_or_alias": training["registered_model_version"],
                "features": [[0.0]],
            },
        )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == "An external model service operation failed."
    assert "registered artifact unavailable" not in detail

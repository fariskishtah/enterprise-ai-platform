"""Fitted-model registry contracts and isolated MLflow adapter tests."""

from pathlib import Path

import joblib  # type: ignore[import-untyped]
import pytest
from app.ml.artifacts import ArtifactFormat, ArtifactInfo
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.registry import (
    MLflowModelRegistry,
    ModelRegistrationRequest,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
    RegisteredModelVersionStatus,
    RegistryMetadataError,
    build_registered_model_name,
    validate_registered_model_name,
)
from app.ml.tracking import ExperimentRunRequest, MLflowExperimentTracker
from mlflow.tracking import MlflowClient


def _key(task_type: TaskType = TaskType.REGRESSION) -> TrainerKey:
    return TrainerKey(AlgorithmType.RANDOM_FOREST, task_type)


def _tracked_artifact(tmp_path: Path) -> tuple[str, str, str]:
    model_path = tmp_path / "model.joblib"
    joblib.dump({"model": "registry"}, model_path)
    artifact = ArtifactInfo(
        path=model_path,
        size_bytes=model_path.stat().st_size,
        format=ArtifactFormat.JOBLIB,
    )
    tracking_uri = f"file:{tmp_path / 'mlruns'}"
    tracking = MLflowExperimentTracker(tracking_uri=tracking_uri).log_successful_run(
        ExperimentRunRequest(
            experiment_name="Registry Integration",
            run_name=None,
            key=_key(),
            parameters={"n_estimators": 5},
            metrics={"mae": 0.25},
            artifact=artifact,
            tags={"purpose": "registry-test"},
        ),
    )
    return tracking_uri, tracking.run_id, tracking.artifact_uri


def _registration_request(tmp_path: Path) -> tuple[str, ModelRegistrationRequest]:
    tracking_uri, run_id, artifact_uri = _tracked_artifact(tmp_path)
    return tracking_uri, ModelRegistrationRequest(
        registered_model_name=build_registered_model_name(_key()),
        source_run_id=run_id,
        artifact_uri=artifact_uri,
        key=_key(),
        description="Registered regression model",
        tags={"purpose": "registry-test"},
    )


def test_registered_model_naming_is_deterministic_and_safe() -> None:
    """Platform defaults derive only from a validated prefix and trainer key."""
    assert build_registered_model_name(_key()) == ("ai_core_random_forest_regression")
    assert (
        build_registered_model_name(
            _key(TaskType.CLASSIFICATION),
            prefix="manufacturing_ai",
        )
        == "manufacturing_ai_random_forest_classification"
    )

    with pytest.raises(ModelRegistryValidationError):
        validate_registered_model_name("Unsafe Model/../../name")
    with pytest.raises(ModelRegistryValidationError):
        build_registered_model_name(_key(), prefix="Unsafe-Prefix")


def test_registration_returns_typed_version_and_protected_tags(tmp_path: Path) -> None:
    """Completed run artifacts become typed READY versions without promotion."""
    tracking_uri, request = _registration_request(tmp_path)
    registry = MLflowModelRegistry(tracking_uri=tracking_uri)

    version = registry.register(request)
    resolved = registry.resolve(version.registered_model_name, version.version)
    raw_version = MlflowClient(tracking_uri=tracking_uri).get_model_version(
        version.registered_model_name,
        version.version,
    )

    assert version == resolved
    assert version.status is RegisteredModelVersionStatus.READY
    assert version.version == "1"
    assert version.run_id == request.source_run_id
    assert version.source_uri == request.artifact_uri
    assert version.key == _key()
    assert version.aliases == ()
    assert raw_version.tags["algorithm"] == "random_forest"
    assert raw_version.tags["task_type"] == "regression"
    assert raw_version.tags["platform_component"] == "ai_core"
    assert raw_version.tags["purpose"] == "registry-test"
    assert raw_version.current_stage == "None"


def test_registry_resolves_alias_without_automatic_alias_creation(
    tmp_path: Path,
) -> None:
    """Aliases are resolved only after an external explicit assignment."""
    tracking_uri, request = _registration_request(tmp_path)
    registry = MLflowModelRegistry(tracking_uri=tracking_uri)
    version = registry.register(request)
    client = MlflowClient(tracking_uri=tracking_uri)

    client.set_registered_model_alias(
        version.registered_model_name,
        "champion",
        version.version,
    )
    resolved = registry.resolve(version.registered_model_name, "champion")

    assert resolved.version == version.version
    assert resolved.aliases == ("champion",)


def test_registry_reports_missing_version_or_alias(tmp_path: Path) -> None:
    """Missing external model references become a dedicated lookup error."""
    registry = MLflowModelRegistry(tracking_uri=f"file:{tmp_path / 'mlruns'}")

    with pytest.raises(RegisteredModelVersionNotFoundError, match="not found"):
        registry.resolve("ai_core_random_forest_regression", "1")


def test_registration_request_rejects_protected_tags(tmp_path: Path) -> None:
    """User tags cannot override registered-version task identity."""
    _, run_id, artifact_uri = _tracked_artifact(tmp_path)

    with pytest.raises(ModelRegistryValidationError, match="protected"):
        ModelRegistrationRequest(
            registered_model_name="ai_core_random_forest_regression",
            source_run_id=run_id,
            artifact_uri=artifact_uri,
            key=_key(),
            description=None,
            tags={"task_type": "classification"},
        )


def test_registry_rejects_versions_without_platform_metadata(tmp_path: Path) -> None:
    """Raw SDK entities lacking protected tags never escape the adapter."""
    tracking_uri, run_id, artifact_uri = _tracked_artifact(tmp_path)
    client = MlflowClient(tracking_uri=tracking_uri)
    name = "ai_core_unmanaged_regression"
    client.create_registered_model(name)
    raw_version = client.create_model_version(
        name=name,
        source=artifact_uri,
        run_id=run_id,
    )

    with pytest.raises(RegistryMetadataError, match="metadata"):
        MLflowModelRegistry(tracking_uri=tracking_uri).resolve(
            name,
            str(raw_version.version),
        )

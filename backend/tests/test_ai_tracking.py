"""Experiment-tracking contracts and isolated MLflow adapter tests."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import joblib  # type: ignore[import-untyped]
import pytest
from app.ml.artifacts import ArtifactFormat, ArtifactInfo
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.tracking import (
    ExperimentRunRequest,
    ExperimentRunStatus,
    ExperimentTrackingError,
    MLflowExperimentTracker,
    ProtectedTrackingTagError,
    TrackingArtifactError,
    UnsupportedTrackingParameterError,
    normalize_tracking_parameters,
)
from mlflow.tracking import MlflowClient


def _key() -> TrainerKey:
    return TrainerKey(AlgorithmType.RANDOM_FOREST, TaskType.REGRESSION)


def _artifact(tmp_path: Path) -> ArtifactInfo:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "model.joblib"
    joblib.dump({"model": "tracked"}, path)
    return ArtifactInfo(
        path=path,
        size_bytes=path.stat().st_size,
        format=ArtifactFormat.JOBLIB,
    )


def _request(
    tmp_path: Path, *, experiment_name: str = "AI Core Tracking"
) -> ExperimentRunRequest:
    return ExperimentRunRequest(
        experiment_name=experiment_name,
        run_name="regression-run",
        key=_key(),
        parameters={
            "n_estimators": 5,
            "bootstrap": True,
            "max_depth": None,
            "max_features": 0.5,
        },
        metrics={"mae": 0.25, "r2": 0.9},
        artifact=_artifact(tmp_path),
        tags={"purpose": "tracking-test"},
    )


def _assign_attribute(instance: object, name: str, value: object) -> None:
    setattr(instance, name, value)


def test_tracking_request_copies_mappings_and_is_immutable(tmp_path: Path) -> None:
    """Caller-owned mappings cannot mutate a validated tracking request."""
    parameters: dict[str, str | int | float | bool | None] = {"n_estimators": 5}
    tags = {"purpose": "initial"}
    request = ExperimentRunRequest(
        experiment_name="immutable",
        run_name=None,
        key=_key(),
        parameters=parameters,
        metrics={"mae": 0.5},
        artifact=_artifact(tmp_path),
        tags=tags,
    )

    parameters["n_estimators"] = 100
    tags["purpose"] = "changed"

    assert request.parameters["n_estimators"] == 5
    assert request.tags["purpose"] == "initial"
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(request, "experiment_name", "changed")


def test_parameter_normalization_rejects_arbitrary_objects() -> None:
    """Unsupported values are rejected instead of stringified implicitly."""
    with pytest.raises(UnsupportedTrackingParameterError, match="finite scalar"):
        normalize_tracking_parameters({"nested": ["not", "scalar"]})


def test_tracking_request_rejects_protected_tag_overrides(tmp_path: Path) -> None:
    """Caller tags cannot replace deterministic AI Core tags."""
    with pytest.raises(ProtectedTrackingTagError, match="protected"):
        ExperimentRunRequest(
            experiment_name="protected",
            run_name=None,
            key=_key(),
            parameters={},
            metrics={},
            artifact=_artifact(tmp_path),
            tags={"algorithm": "user-value"},
        )


def test_mlflow_tracker_logs_successful_run_and_resolves_experiment(
    tmp_path: Path,
) -> None:
    """One experiment is reused while each successful request gets one run."""
    tracking_uri = f"file:{tmp_path / 'mlruns'}"
    tracker = MLflowExperimentTracker(tracking_uri=tracking_uri)

    first = tracker.log_successful_run(_request(tmp_path / "first"))
    second = tracker.log_successful_run(_request(tmp_path / "second"))

    client = MlflowClient(tracking_uri=tracking_uri)
    run = client.get_run(first.run_id)
    artifacts = client.list_artifacts(first.run_id, path="model")

    assert first.experiment_id == second.experiment_id
    assert first.run_id != second.run_id
    assert first.status is ExperimentRunStatus.FINISHED
    assert run.info.status == "FINISHED"
    assert run.data.tags["algorithm"] == "random_forest"
    assert run.data.tags["task_type"] == "regression"
    assert run.data.tags["platform_component"] == "ai_core"
    assert run.data.tags["model_format"] == "joblib"
    assert run.data.tags["purpose"] == "tracking-test"
    assert run.data.params["bootstrap"] == "true"
    assert run.data.params["max_depth"] == "null"
    assert run.data.metrics == {"mae": 0.25, "r2": 0.9}
    assert [artifact.path for artifact in artifacts] == ["model/model.joblib"]
    assert first.artifact_uri.endswith("/model/model.joblib")


def test_tracker_rejects_missing_artifact_before_creating_run(tmp_path: Path) -> None:
    """An unavailable local artifact never produces a successful MLflow run."""
    missing = ArtifactInfo(
        path=tmp_path / "missing.joblib",
        size_bytes=1,
        format=ArtifactFormat.JOBLIB,
    )
    request = ExperimentRunRequest(
        experiment_name="missing-artifact",
        run_name=None,
        key=_key(),
        parameters={},
        metrics={},
        artifact=missing,
        tags={},
    )

    with pytest.raises(TrackingArtifactError, match="not available"):
        MLflowExperimentTracker(
            tracking_uri=f"file:{tmp_path / 'mlruns'}",
        ).log_successful_run(request)


def test_tracker_marks_started_run_failed_when_logging_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter failures close an already-started MLflow run as FAILED."""
    tracking_uri = f"file:{tmp_path / 'mlruns'}"
    request = _request(tmp_path)

    def fail_log_artifact(
        _client: MlflowClient,
        _run_id: str,
        _local_path: str,
        artifact_path: str | None = None,
    ) -> None:
        _ = artifact_path
        raise RuntimeError("sentinel artifact failure")

    monkeypatch.setattr(MlflowClient, "log_artifact", fail_log_artifact)

    with pytest.raises(ExperimentTrackingError, match="could not log"):
        MLflowExperimentTracker(tracking_uri=tracking_uri).log_successful_run(request)

    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name(request.experiment_name)
    assert experiment is not None
    runs = client.search_runs([str(experiment.experiment_id)])
    assert len(runs) == 1
    assert runs[0].info.status == "FAILED"

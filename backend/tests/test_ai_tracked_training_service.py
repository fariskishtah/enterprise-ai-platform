"""Ordered tracked-training application service tests."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import assert_type

import numpy as np
import pytest
from app.ml.artifacts import LocalArtifactManager
from app.ml.base import TrainerInput
from app.ml.composition import create_random_forest_regression_plan
from app.ml.engine import TrainingEngine, TrainingExecutionPlan
from app.ml.factory import TrainerFactory, TrainerRegistry
from app.ml.metrics import RegressionMetricsReport
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationError,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
    RegisteredModelVersionStatus,
    build_registered_model_name,
)
from app.ml.services import (
    TrackedTrainingRequest,
    TrackedTrainingResult,
    TrackedTrainingService,
)
from app.ml.tracking import (
    BaseExperimentTracker,
    ExperimentRunInfo,
    ExperimentRunRequest,
    ExperimentRunStatus,
    ExperimentTrackingError,
)
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    RandomForestRegressorTrainer,
    TrainerDataValidationError,
)
from app.ml.trainers.random_forest.types import (
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
)
from sklearn.ensemble import RandomForestRegressor  # type: ignore[import-untyped]

FEATURES: FeatureArray = np.array(
    [[0.0], [1.0], [2.0], [3.0]],
    dtype=np.float64,
)
TARGETS: RegressionTargetArray = np.array(
    [0.0, 1.0, 2.0, 3.0],
    dtype=np.float64,
)


@dataclass
class RecordingTracker(BaseExperimentTracker):
    """Record requests and optionally fail after local execution."""

    events: list[str]
    failure: ExperimentTrackingError | None = None
    requests: list[ExperimentRunRequest] = field(default_factory=list)

    def log_successful_run(
        self,
        request: ExperimentRunRequest,
    ) -> ExperimentRunInfo:
        self.events.append("tracking")
        self.requests.append(request)
        assert request.artifact.path.is_file()
        if self.failure is not None:
            raise self.failure
        return ExperimentRunInfo(
            experiment_id="experiment-1",
            run_id="mlflow-run-1",
            artifact_uri="file:///tracked/model/model.joblib",
            status=ExperimentRunStatus.FINISHED,
        )


@dataclass
class RecordingRegistry(BaseModelRegistry):
    """Record registrations and optionally fail after tracking."""

    events: list[str]
    failure: ModelRegistrationError | None = None
    requests: list[ModelRegistrationRequest] = field(default_factory=list)

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        self.events.append("registry")
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return RegisteredModelVersion(
            registered_model_name=request.registered_model_name,
            version="1",
            run_id=request.source_run_id,
            source_uri=request.artifact_uri,
            key=request.key,
            status=RegisteredModelVersionStatus.READY,
            aliases=(),
        )

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        _ = (registered_model_name, version_or_alias)
        raise RegisteredModelVersionNotFoundError("not used by training tests")


def _plan(
    *,
    features: FeatureArray = FEATURES,
) -> TrainingExecutionPlan[
    RandomForestRegressorTrainer,
    FeatureArray,
    RegressionTargetArray,
    RandomForestRegressor,
    RegressionPredictionArray,
    RegressionMetricsReport,
]:
    return create_random_forest_regression_plan(
        training_input=TrainerInput(
            features=features,
            targets=TARGETS,
            hyperparameters={"n_estimators": 3, "n_jobs": 1},
            random_seed=7,
        ),
        evaluation_features=FEATURES,
        evaluation_targets=TARGETS,
    )


def _request(
    *,
    plan: TrainingExecutionPlan[
        RandomForestRegressorTrainer,
        FeatureArray,
        RegressionTargetArray,
        RandomForestRegressor,
        RegressionPredictionArray,
        RegressionMetricsReport,
    ],
) -> TrackedTrainingRequest[
    RandomForestRegressorTrainer,
    FeatureArray,
    RegressionTargetArray,
    RandomForestRegressor,
    RegressionPredictionArray,
    RegressionMetricsReport,
]:
    return TrackedTrainingRequest(
        plan=plan,
        experiment_name="Tracked Service",
        run_name="regression",
        registered_model_name=build_registered_model_name(
            RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
        ),
        tracking_parameters={"n_estimators": 3, "workflow_random_seed": 7},
        tracking_tags={"purpose": "service-test"},
        model_description="Tracked service model",
    )


def _service(
    tmp_path: Path,
    tracker: BaseExperimentTracker,
    registry: BaseModelRegistry,
) -> TrackedTrainingService:
    trainer_registry = TrainerRegistry()
    trainer_registry.register(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    return TrackedTrainingService(
        training_engine=TrainingEngine(
            trainer_factory=TrainerFactory(trainer_registry),
            artifact_manager=LocalArtifactManager(tmp_path / "artifacts"),
        ),
        experiment_tracker=tracker,
        model_registry=registry,
    )


def test_tracked_training_orders_local_tracking_and_registration(
    tmp_path: Path,
) -> None:
    """A combined result is returned only after all ordered stages succeed."""
    events: list[str] = []
    tracker = RecordingTracker(events)
    registry = RecordingRegistry(events)

    result = _service(tmp_path, tracker, registry).execute(_request(plan=_plan()))

    assert_type(
        result,
        TrackedTrainingResult[RandomForestRegressor, RegressionMetricsReport],
    )
    assert events == ["tracking", "registry"]
    assert result.execution.artifact.path.is_file()
    assert result.tracking.run_id == "mlflow-run-1"
    assert result.registered_model.version == "1"
    assert tracker.requests[0].metrics == result.execution.metrics_report.to_mapping()
    assert registry.requests[0].source_run_id == result.tracking.run_id


def test_training_failure_prevents_tracking_and_registration(tmp_path: Path) -> None:
    """Invalid local training never creates external successful state."""
    events: list[str] = []
    tracker = RecordingTracker(events)
    registry = RecordingRegistry(events)
    invalid_features: FeatureArray = np.array([0.0, 1.0], dtype=np.float64)

    with pytest.raises(TrainerDataValidationError, match="2-dimensional"):
        _service(tmp_path, tracker, registry).execute(
            _request(plan=_plan(features=invalid_features)),
        )

    assert events == []
    assert tracker.requests == []
    assert registry.requests == []


def test_tracking_failure_preserves_local_artifact_and_skips_registry(
    tmp_path: Path,
) -> None:
    """A tracking failure leaves local recovery state and no registry version."""
    events: list[str] = []
    tracker = RecordingTracker(
        events,
        failure=ExperimentTrackingError("tracking unavailable"),
    )
    registry = RecordingRegistry(events)

    with pytest.raises(ExperimentTrackingError, match="unavailable"):
        _service(tmp_path, tracker, registry).execute(_request(plan=_plan()))

    assert events == ["tracking"]
    assert len(tuple((tmp_path / "artifacts").rglob("model.joblib"))) == 1
    assert registry.requests == []


def test_registry_failure_preserves_tracking_and_local_artifact(tmp_path: Path) -> None:
    """Registration failure does not fake success or roll back completed stages."""
    events: list[str] = []
    tracker = RecordingTracker(events)
    registry = RecordingRegistry(
        events,
        failure=ModelRegistrationError("registry unavailable"),
    )

    with pytest.raises(ModelRegistrationError, match="unavailable"):
        _service(tmp_path, tracker, registry).execute(_request(plan=_plan()))

    assert events == ["tracking", "registry"]
    assert len(tracker.requests) == 1
    assert len(registry.requests) == 1
    assert len(tuple((tmp_path / "artifacts").rglob("model.joblib"))) == 1

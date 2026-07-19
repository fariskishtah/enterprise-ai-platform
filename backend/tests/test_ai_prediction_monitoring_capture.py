"""Resilient monitored-prediction orchestration tests."""

import asyncio
from dataclasses import dataclass, field
from time import perf_counter as real_perf_counter
from typing import cast
from uuid import uuid4

import app.ml.monitoring.capture as monitoring_capture_module
import numpy as np
import pytest
from app.ml.base import TrainerInput
from app.ml.composition import create_random_forest_regression_prediction_plan
from app.ml.monitoring import (
    ModelReferenceProfile,
    MonitoredPredictionService,
    PredictionCaptureContext,
    PredictionCaptureHealth,
    PredictionEvent,
    PredictionEventStatus,
)
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
    RegisteredModelVersionStatus,
)
from app.ml.services import (
    BaseRegisteredModelLoader,
    PredictionService,
    RegisteredModelTypeMismatchError,
    RegisteredPredictionRequest,
)
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    RandomForestRegressorTrainer,
)
from app.ml.trainers.random_forest.types import (
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
)
from sklearn.ensemble import RandomForestRegressor  # type: ignore[import-untyped]

FEATURES: FeatureArray = np.asarray(
    [[0.0], [1.0], [2.0], [3.0]],
    dtype=np.float64,
)
TARGETS: RegressionTargetArray = np.asarray(
    [0.0, 1.0, 2.0, 3.0],
    dtype=np.float64,
)


@dataclass
class FakeRegistry(BaseModelRegistry):
    """Resolve one version or fail before any model load."""

    version: RegisteredModelVersion | None
    resolve_count: int = 0

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        _ = request
        raise AssertionError("Prediction capture must not register models.")

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        _ = (registered_model_name, version_or_alias)
        self.resolve_count += 1
        if self.version is None:
            raise RegisteredModelVersionNotFoundError("private missing detail")
        return self.version


@dataclass
class FakeLoader(BaseRegisteredModelLoader):
    """Return one checked fitted estimator and count deserializations."""

    model: object
    load_count: int = 0

    def load[
        ModelT
    ](
        self,
        model_version: RegisteredModelVersion,
        expected_type: type[ModelT],
    ) -> ModelT:
        _ = model_version
        self.load_count += 1
        if not isinstance(self.model, expected_type):
            raise RegisteredModelTypeMismatchError("wrong model")
        return self.model


@dataclass
class FakeEventStore:
    """In-memory persistence port with an optional deterministic outage."""

    fail: bool = False
    delay_seconds: float = 0.0
    events: list[PredictionEvent] = field(default_factory=list)
    commit_count: int = 0
    rollback_count: int = 0

    async def create_event(self, event: PredictionEvent) -> PredictionEvent:
        if self.fail:
            raise OSError("private database failure")
        self.events.append(event)
        return event

    async def get_reference_profile(
        self,
        registered_model_name: str,
        model_version: str,
    ) -> ModelReferenceProfile | None:
        _ = (registered_model_name, model_version)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise OSError("private database failure")
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def _version() -> RegisteredModelVersion:
    return RegisteredModelVersion(
        registered_model_name="ai_core_random_forest_regression",
        version="7",
        run_id="run-7",
        source_uri="file:///model.joblib",
        key=RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
        status=RegisteredModelVersionStatus.READY,
        aliases=("champion",),
    )


def _model() -> RandomForestRegressor:
    return (
        RandomForestRegressorTrainer()
        .fit(
            TrainerInput(
                features=FEATURES,
                targets=TARGETS,
                hyperparameters={"n_estimators": 3, "n_jobs": 1},
                random_seed=17,
            ),
        )
        .model
    )


def test_capture_failure_health_is_instance_local_and_restart_resetting() -> None:
    """Independent process instances neither share nor retain diagnostic counts."""
    serving_instance = PredictionCaptureHealth()
    other_replica_or_restarted_instance = PredictionCaptureHealth()

    serving_instance.record_persistence_failure()
    serving_instance.record_persistence_failure()

    assert serving_instance.snapshot().instance_capture_failures_since_start == 2
    assert (
        other_replica_or_restarted_instance.snapshot().instance_capture_failures_since_start
        == 0
    )


@pytest.mark.anyio
async def test_successful_prediction_creates_one_safe_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capture preserves exact resolution, request shape, and output summary."""
    metric_labels: list[dict[str, object]] = []
    monkeypatch.setattr(
        monitoring_capture_module,
        "record_prediction",
        lambda **labels: metric_labels.append(labels),
    )
    registry = FakeRegistry(_version())
    loader = FakeLoader(_model())
    store = FakeEventStore()
    service = MonitoredPredictionService(
        prediction_service=PredictionService(
            model_registry=registry,
            model_loader=loader,
        ),
        event_store=store,
        capture_health=PredictionCaptureHealth(),
    )

    result = await service.predict(
        create_random_forest_regression_prediction_plan(),
        RegisteredPredictionRequest(
            "ai_core_random_forest_regression",
            "champion",
            FEATURES,
        ),
        PredictionCaptureContext(uuid4(), "request-17"),
    )

    assert result.predictions.shape == (4,)
    assert registry.resolve_count == 1
    assert loader.load_count == 1
    assert store.commit_count == 1
    assert len(store.events) == 1
    event = store.events[0]
    assert event.status is PredictionEventStatus.SUCCEEDED
    assert event.resolved_model_version == "7"
    assert event.resolved_aliases == ("champion",)
    assert event.row_count == 4
    assert event.feature_count == 1
    assert event.correlation_id == "request-17"
    assert metric_labels == [
        {
            "task_type": "regression",
            "algorithm": "random_forest",
            "final_status": "succeeded",
            "row_count": 4,
        }
    ]


@pytest.mark.anyio
async def test_capture_outage_does_not_change_or_repeat_successful_prediction() -> None:
    """Monitoring degradation is observable and never reruns prediction."""
    registry = FakeRegistry(_version())
    loader = FakeLoader(_model())
    store = FakeEventStore(fail=True)
    health = PredictionCaptureHealth()
    service = MonitoredPredictionService(
        prediction_service=PredictionService(
            model_registry=registry,
            model_loader=loader,
        ),
        event_store=store,
        capture_health=health,
    )

    result = await service.predict(
        create_random_forest_regression_prediction_plan(),
        RegisteredPredictionRequest(
            "ai_core_random_forest_regression",
            "7",
            FEATURES,
        ),
        PredictionCaptureContext(uuid4()),
    )

    assert result.predictions.shape == (4,)
    assert registry.resolve_count == 1
    assert loader.load_count == 1
    assert store.rollback_count == 1
    assert health.snapshot().instance_capture_failures_since_start == 1


@pytest.mark.anyio
async def test_slow_recorder_is_excluded_from_prediction_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monitoring delay cannot inflate execution latency or repeat prediction."""
    model = _model()
    original_predict = model.predict
    expected_predictions = cast(
        RegressionPredictionArray,
        original_predict(FEATURES),
    )
    prediction_count = 0

    def counted_predict(features: FeatureArray) -> RegressionPredictionArray:
        nonlocal prediction_count
        prediction_count += 1
        return cast(RegressionPredictionArray, original_predict(features))

    monkeypatch.setattr(model, "predict", counted_predict)
    clock_values = iter((10.0, 10.005))
    monkeypatch.setattr(
        "app.ml.monitoring.capture.perf_counter",
        lambda: next(clock_values),
    )
    registry = FakeRegistry(_version())
    loader = FakeLoader(model)
    store = FakeEventStore(delay_seconds=0.1)
    service = MonitoredPredictionService(
        prediction_service=PredictionService(
            model_registry=registry,
            model_loader=loader,
        ),
        event_store=store,
        capture_health=PredictionCaptureHealth(),
    )

    wall_started = real_perf_counter()
    result = await service.predict(
        create_random_forest_regression_prediction_plan(),
        RegisteredPredictionRequest(
            "ai_core_random_forest_regression",
            "champion",
            FEATURES,
        ),
        PredictionCaptureContext(uuid4()),
    )
    wall_duration = real_perf_counter() - wall_started

    assert prediction_count == 1
    assert registry.resolve_count == 1
    assert loader.load_count == 1
    np.testing.assert_allclose(result.predictions, expected_predictions)
    assert len(store.events) == 1
    assert store.events[0].duration_ms == pytest.approx(5.0)
    assert wall_duration >= 0.09


@pytest.mark.anyio
async def test_resolution_failure_creates_sanitized_failed_event() -> None:
    """A valid authenticated attempt logs a stable code, never private detail."""
    store = FakeEventStore()
    service = MonitoredPredictionService(
        prediction_service=PredictionService(
            model_registry=FakeRegistry(None),
            model_loader=FakeLoader(_model()),
        ),
        event_store=store,
        capture_health=PredictionCaptureHealth(),
    )

    with pytest.raises(RegisteredModelVersionNotFoundError):
        await service.predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                "ai_core_random_forest_regression",
                "missing",
                FEATURES,
            ),
            PredictionCaptureContext(uuid4()),
        )

    assert len(store.events) == 1
    event = store.events[0]
    assert event.status is PredictionEventStatus.FAILED
    assert event.resolved_model_version is None
    assert event.error_code == "model_version_not_found"
    assert event.safe_error_message == "The requested model version was not found."
    assert "private" not in event.safe_error_message


@pytest.mark.anyio
async def test_capture_outage_preserves_original_prediction_exception() -> None:
    """Monitoring failure never replaces or retries the prediction error."""
    store = FakeEventStore(fail=True)
    health = PredictionCaptureHealth()
    registry = FakeRegistry(None)
    service = MonitoredPredictionService(
        prediction_service=PredictionService(
            model_registry=registry,
            model_loader=FakeLoader(_model()),
        ),
        event_store=store,
        capture_health=health,
    )

    with pytest.raises(RegisteredModelVersionNotFoundError):
        await service.predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                "ai_core_random_forest_regression",
                "missing",
                FEATURES,
            ),
            PredictionCaptureContext(uuid4()),
        )

    assert registry.resolve_count == 1
    assert store.rollback_count == 1
    assert health.snapshot().instance_capture_failures_since_start == 1


@pytest.mark.anyio
async def test_post_resolution_failure_retains_exact_version_context() -> None:
    """Load failures remain attributable to the exact resolved model version."""
    store = FakeEventStore()
    service = MonitoredPredictionService(
        prediction_service=PredictionService(
            model_registry=FakeRegistry(_version()),
            model_loader=FakeLoader(object()),
        ),
        event_store=store,
        capture_health=PredictionCaptureHealth(),
    )

    with pytest.raises(RegisteredModelTypeMismatchError):
        await service.predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                "ai_core_random_forest_regression",
                "champion",
                FEATURES,
            ),
            PredictionCaptureContext(uuid4()),
        )

    event = store.events[0]
    assert event.status is PredictionEventStatus.FAILED
    assert event.resolved_model_version == "7"
    assert event.resolved_aliases == ("champion",)
    assert event.error_code == "model_type_mismatch"

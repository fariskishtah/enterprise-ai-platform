"""Prediction monitoring aggregation, coverage, and truncation tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring import (
    DriftDetectionEngine,
    DriftSeverity,
    DriftThresholds,
    ModelReferenceProfile,
    PredictionCaptureHealth,
    PredictionEvent,
    PredictionEventPage,
    PredictionEventStatus,
    build_model_reference_profile,
    feature_request_profiles,
    prediction_request_profile,
)
from app.ml.monitoring.models import OperationalAggregate
from app.ml.monitoring.service import PredictionMonitoringService, calculate_percentile
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionStatus,
)
from app.ml.trainers.random_forest.types import FeatureArray, RegressionPredictionArray
from app.repositories.ai_monitoring import PredictionMonitoringRepository

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)
KEY = TrainerKey(AlgorithmType.RANDOM_FOREST, TaskType.REGRESSION)


class FakeRegistry(BaseModelRegistry):
    """Resolve one exact version without mutating the registry."""

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        _ = request
        raise AssertionError("Monitoring must not register models.")

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        _ = version_or_alias
        return RegisteredModelVersion(
            registered_model_name=registered_model_name,
            version="7",
            run_id="run-7",
            source_uri="file:///model.joblib",
            key=KEY,
            status=RegisteredModelVersionStatus.READY,
            aliases=("champion",),
        )


class FakeMonitoringRepository(PredictionMonitoringRepository):
    """Return bounded newest-event fixtures without a database dependency."""

    def __init__(
        self,
        *,
        page: PredictionEventPage,
        durations: tuple[float, ...] = (),
        aggregate: OperationalAggregate | None = None,
    ) -> None:
        self.page = page
        self.durations = durations
        self.aggregate = aggregate or OperationalAggregate(
            request_count=page.total,
            success_count=page.total,
            failure_count=0,
            duration_total_ms=sum(durations),
            minimum_duration_ms=min(durations) if durations else None,
            maximum_duration_ms=max(durations) if durations else None,
            total_predicted_rows=page.total,
            failures_by_error_code={},
        )
        self.reference = _reference()

    async def aggregate_operations(
        self,
        *,
        registered_model_name: str,
        resolved_model_version: str,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime,
        end_at: datetime,
    ) -> OperationalAggregate:
        _ = (
            registered_model_name,
            resolved_model_version,
            task_type,
            status,
            start_at,
            end_at,
        )
        return self.aggregate

    async def list_durations(
        self,
        *,
        registered_model_name: str,
        resolved_model_version: str,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[float, ...]:
        _ = (
            registered_model_name,
            resolved_model_version,
            task_type,
            status,
            start_at,
            end_at,
        )
        assert limit == 2
        return self.durations

    async def get_reference_profile(
        self,
        registered_model_name: str,
        model_version: str,
    ) -> ModelReferenceProfile | None:
        assert registered_model_name == self.reference.registered_model_name
        assert model_version == self.reference.model_version
        return self.reference

    async def list_window_events(
        self,
        *,
        registered_model_name: str,
        resolved_model_version: str,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> PredictionEventPage:
        _ = (registered_model_name, resolved_model_version, start_at, end_at)
        assert limit == 2
        return self.page


def _reference() -> ModelReferenceProfile:
    features: FeatureArray = np.arange(4, dtype=np.float64).reshape(4, 1)
    predictions: RegressionPredictionArray = np.arange(4, dtype=np.float64)
    return build_model_reference_profile(
        profile_id=uuid4(),
        training_job_id=uuid4(),
        registered_model_name="ai_core_random_forest_regression",
        model_version="7",
        key=KEY,
        evaluation_features=features,
        predictions=predictions,
        bin_count=10,
        created_at=NOW,
    )


def _event(*, status: PredictionEventStatus) -> PredictionEvent:
    reference = _reference()
    features: FeatureArray = np.asarray([[1.0]], dtype=np.float64)
    predictions: RegressionPredictionArray = np.asarray([1.0], dtype=np.float64)
    return PredictionEvent(
        id=uuid4(),
        requested_by_user_id=uuid4(),
        registered_model_name=reference.registered_model_name,
        requested_model_reference="champion",
        resolved_model_version=reference.model_version,
        resolved_aliases=("champion",),
        key=KEY,
        status=status,
        row_count=1,
        feature_count=1,
        duration_ms=5.0,
        feature_profile=feature_request_profiles(features, reference),
        prediction_profile=(
            prediction_request_profile(predictions, key=KEY, reference=reference)
            if status is PredictionEventStatus.SUCCEEDED
            else None
        ),
        error_code=None if status is PredictionEventStatus.SUCCEEDED else "failed",
        safe_error_message=(
            None if status is PredictionEventStatus.SUCCEEDED else "Prediction failed."
        ),
        correlation_id=None,
        created_at=NOW,
        completed_at=NOW + timedelta(milliseconds=5),
    )


def _service(
    repository: PredictionMonitoringRepository,
    *,
    health: PredictionCaptureHealth | None = None,
) -> PredictionMonitoringService:
    return PredictionMonitoringService(
        repository=repository,
        model_registry=FakeRegistry(),
        drift_engine=DriftDetectionEngine(),
        capture_health=health or PredictionCaptureHealth(),
        minimum_sample_count=2,
        maximum_window_days=30,
        maximum_events_per_window=2,
        thresholds=DriftThresholds(
            warning=0.1,
            critical=0.25,
            missing_rate_warning=0.05,
            out_of_range_warning=0.1,
        ),
    )


def test_portable_percentiles_are_deterministic() -> None:
    """Bounded ordered durations use documented linear interpolation."""
    values = (10.0, 20.0, 30.0, 40.0)

    assert calculate_percentile(values, 0.50) == 25.0
    assert calculate_percentile(values, 0.95) == pytest.approx(38.5)
    assert calculate_percentile(values, 0.99) == pytest.approx(39.7)
    assert calculate_percentile((), 0.50) is None


@pytest.mark.anyio
async def test_operations_separates_totals_percentiles_and_instance_health() -> None:
    """The instance diagnostic is neither window math nor a durable event count."""
    health = PredictionCaptureHealth()
    health.record_persistence_failure()
    health.record_persistence_failure()
    aggregate = OperationalAggregate(
        request_count=3,
        success_count=2,
        failure_count=1,
        duration_total_ms=36.0,
        minimum_duration_ms=1.0,
        maximum_duration_ms=20.0,
        total_predicted_rows=3,
        failures_by_error_code={"model_load_failed": 1},
    )
    repository = FakeMonitoringRepository(
        page=PredictionEventPage((), 3),
        durations=(15.0, 20.0),
        aggregate=aggregate,
    )

    service = _service(repository, health=health)
    summary = await service.operations(
        registered_model_name="ai_core_random_forest_regression",
        version_or_alias="champion",
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        task_type=None,
        status=None,
    )
    other_window = await service.operations(
        registered_model_name="ai_core_random_forest_regression",
        version_or_alias="champion",
        start_at=NOW - timedelta(hours=3),
        end_at=NOW - timedelta(hours=2),
        task_type=None,
        status=None,
    )

    assert summary.request_count == 3
    assert summary.failure_count == 1
    assert summary.matched_event_count == 3
    assert summary.analyzed_event_count == 2
    assert summary.truncated is True
    assert summary.analysis_warning is not None
    assert summary.p50_latency_ms == 17.5
    assert summary.instance_capture_failures_since_start == 2
    assert other_window.instance_capture_failures_since_start == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("matched_count", "expected_truncated"),
    ((2, False), (3, True)),
)
async def test_data_quality_discloses_exact_limit_and_one_over_limit(
    matched_count: int,
    expected_truncated: bool,
) -> None:
    """The newest bounded set is complete at the cap and partial one event over."""
    events = (
        _event(status=PredictionEventStatus.SUCCEEDED),
        _event(status=PredictionEventStatus.SUCCEEDED),
    )
    repository = FakeMonitoringRepository(
        page=PredictionEventPage(events, matched_count),
    )

    report = await _service(repository).data_quality(
        registered_model_name="ai_core_random_forest_regression",
        version_or_alias="champion",
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
    )

    assert report.matched_event_count == matched_count
    assert report.analyzed_event_count == 2
    assert report.request_count == 2
    assert report.truncated is expected_truncated
    assert (report.analysis_warning is not None) is expected_truncated


@pytest.mark.anyio
async def test_drift_uses_only_analyzed_events_for_sample_sufficiency() -> None:
    """An excluded older success cannot turn a partial newest window sufficient."""
    newest_events = (
        _event(status=PredictionEventStatus.FAILED),
        _event(status=PredictionEventStatus.SUCCEEDED),
    )
    repository = FakeMonitoringRepository(
        page=PredictionEventPage(newest_events, 3),
    )

    report = await _service(repository).drift(
        registered_model_name="ai_core_random_forest_regression",
        version_or_alias="champion",
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        minimum_sample_count=2,
    )

    assert report.matched_event_count == 3
    assert report.analyzed_event_count == 2
    assert report.current_sample_count == 1
    assert report.truncated is True
    assert report.analysis_warning is not None
    assert report.aggregate_status is DriftSeverity.INSUFFICIENT_DATA

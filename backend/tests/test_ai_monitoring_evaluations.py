"""Persisted monitoring evaluation, status, and alert lifecycle tests."""

from datetime import UTC, datetime, timedelta

import pytest
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring import (
    DriftSeverity,
    DriftThresholds,
    FeatureDriftResult,
    ModelDriftReport,
    MonitoringNotFoundError,
    PredictionDataQualityReport,
    PredictionOperationalSummary,
    ReferenceProfileSource,
    RegressionPredictionDrift,
)
from app.ml.monitoring.alert_service import MonitoringAlertService
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertStatus,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
)
from app.ml.monitoring.evaluation_service import (
    MonitoringEvaluationService,
    derive_overall_status,
)
from app.ml.registry import RegisteredModelVersion, RegisteredModelVersionStatus
from app.repositories.monitoring_alerts import MonitoringAlertRepository
from app.repositories.monitoring_evaluations import MonitoringEvaluationRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)
START = NOW - timedelta(hours=24)
KEY = TrainerKey(AlgorithmType.RANDOM_FOREST, TaskType.REGRESSION)


class FakeRegistry:
    def resolve(self, name: str, reference: str) -> RegisteredModelVersion:
        assert name == "factory_quality"
        assert reference in {"1", "champion"}
        return RegisteredModelVersion(
            registered_model_name=name,
            version="1",
            run_id="run-1",
            source_uri="models:/factory_quality/1",
            key=KEY,
            status=RegisteredModelVersionStatus.READY,
            aliases=("champion",),
        )


class FakeMonitoring:
    def __init__(
        self,
        *,
        drift_status: DriftSeverity = DriftSeverity.STABLE,
        missing_reference: bool = False,
        failure_count: int = 0,
        sample_count: int = 25,
    ) -> None:
        self.drift_status = drift_status
        self.missing_reference = missing_reference
        self.failure_count = failure_count
        self.sample_count = sample_count

    async def reference_profile(self, **arguments: object) -> object:
        _ = arguments
        if self.missing_reference:
            raise MonitoringNotFoundError("missing")
        return object()

    async def operations(self, **arguments: object) -> PredictionOperationalSummary:
        _ = arguments
        success_count = 5
        total = success_count + self.failure_count
        return PredictionOperationalSummary(
            registered_model_name="factory_quality",
            model_version="1",
            start_at=START,
            end_at=NOW,
            request_count=total,
            success_count=success_count,
            failure_count=self.failure_count,
            success_rate=success_count / total,
            failure_rate=self.failure_count / total,
            average_latency_ms=10.0,
            minimum_latency_ms=5.0,
            maximum_latency_ms=20.0,
            p50_latency_ms=10.0,
            p95_latency_ms=19.0,
            p99_latency_ms=20.0,
            total_predicted_rows=self.sample_count,
            average_batch_size=self.sample_count / total,
            failures_by_error_code=(
                {"model_load_failed": self.failure_count} if self.failure_count else {}
            ),
            matched_event_count=total,
            analyzed_event_count=total,
            truncated=False,
            analysis_warning=None,
            instance_capture_failures_since_start=0,
        )

    async def data_quality(self, **arguments: object) -> PredictionDataQualityReport:
        _ = arguments
        return PredictionDataQualityReport(
            registered_model_name="factory_quality",
            model_version="1",
            start_at=START,
            end_at=NOW,
            request_count=5,
            row_count=self.sample_count,
            missing_value_count=0,
            non_finite_value_count=0,
            feature_count_mismatch_requests=0,
            empty_batch_requests=0,
            constant_column_occurrences=0,
            out_of_reference_range_count=0,
            finite_value_count=self.sample_count,
            out_of_reference_range_proportion=0.0,
            issues=(),
            matched_event_count=5,
            analyzed_event_count=5,
            truncated=False,
            analysis_warning=None,
        )

    async def drift(self, **arguments: object) -> ModelDriftReport:
        _ = arguments
        status = (
            DriftSeverity.INSUFFICIENT_DATA
            if self.sample_count < 20
            else self.drift_status
        )
        return ModelDriftReport(
            registered_model_name="factory_quality",
            model_version="1",
            key=KEY,
            reference_source=ReferenceProfileSource.EVALUATION,
            reference_sample_count=25,
            current_sample_count=self.sample_count,
            start_at=START,
            end_at=NOW,
            feature_results=(
                FeatureDriftResult(0, 0.5, 25, self.sample_count, 0.0, 0.0, status),
            ),
            prediction_result=RegressionPredictionDrift(
                0.5, 0.0, 1.0, 25, self.sample_count, status
            ),
            aggregate_status=status,
            thresholds=DriftThresholds(0.1, 0.25, 0.05, 0.1),
            generated_at=NOW,
            matched_event_count=5,
            analyzed_event_count=5,
            truncated=False,
            analysis_warning=None,
        )


def _service(
    session: AsyncSession, monitoring: FakeMonitoring
) -> MonitoringEvaluationService:
    return MonitoringEvaluationService(
        repository=MonitoringEvaluationRepository(session),
        monitoring_service=monitoring,  # type: ignore[arg-type]
        model_registry=FakeRegistry(),  # type: ignore[arg-type]
        alert_service=MonitoringAlertService(
            repository=MonitoringAlertRepository(session), clock=lambda: NOW
        ),
        minimum_sample_count=20,
        maximum_window_days=30,
        failure_rate_warning_threshold=0.05,
        failure_rate_critical_threshold=0.20,
        clock=lambda: NOW,
    )


def test_overall_status_precedence_is_deterministic() -> None:
    assert derive_overall_status((MonitoringEvaluationStatus.HEALTHY,)) is (
        MonitoringEvaluationStatus.HEALTHY
    )
    assert (
        derive_overall_status(
            (
                MonitoringEvaluationStatus.WARNING,
                MonitoringEvaluationStatus.CRITICAL,
            )
        )
        is MonitoringEvaluationStatus.CRITICAL
    )
    assert (
        derive_overall_status(
            (
                MonitoringEvaluationStatus.CRITICAL,
                MonitoringEvaluationStatus.UNAVAILABLE,
            )
        )
        is MonitoringEvaluationStatus.UNAVAILABLE
    )


@pytest.mark.anyio
async def test_evaluation_persists_exact_version_and_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = _service(session, FakeMonitoring())
        first = await service.evaluate(
            registered_model_name="factory_quality",
            version_or_alias="champion",
            window_start=START,
            window_end=NOW,
            trigger=MonitoringEvaluationTrigger.MANUAL,
            idempotency_key="evaluation-1",
        )
        repeated = await service.evaluate(
            registered_model_name="factory_quality",
            version_or_alias="champion",
            window_start=START,
            window_end=NOW,
            trigger=MonitoringEvaluationTrigger.MANUAL,
            idempotency_key="evaluation-1",
        )
        page = await service.list(
            registered_model_name="factory_quality",
            model_version="1",
            overall_status=None,
            start_at=None,
            end_at=None,
            limit=10,
            offset=0,
        )

    assert first.id == repeated.id
    assert first.model_version == "1"
    assert first.model_alias == "champion"
    assert first.overall_status is MonitoringEvaluationStatus.HEALTHY
    assert page.total == 1
    assert "features" not in first.report
    assert "predictions" not in first.report


@pytest.mark.anyio
async def test_critical_alert_deduplicates_and_healthy_evaluation_resolves_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monitoring = FakeMonitoring(drift_status=DriftSeverity.CRITICAL)
    async with session_factory() as session:
        service = _service(session, monitoring)
        first = await service.evaluate(
            registered_model_name="factory_quality",
            version_or_alias="1",
            window_start=START,
            window_end=NOW,
            trigger=MonitoringEvaluationTrigger.SCHEDULED,
        )
        await service.evaluate(
            registered_model_name="factory_quality",
            version_or_alias="1",
            window_start=START + timedelta(hours=1),
            window_end=NOW + timedelta(hours=1),
            trigger=MonitoringEvaluationTrigger.SCHEDULED,
        )
        alerts = await MonitoringAlertRepository(session).list(
            registered_model_name="factory_quality",
            model_version="1",
            severity=None,
            status=None,
            limit=20,
            offset=0,
        )
        assert first.overall_status is MonitoringEvaluationStatus.CRITICAL
        drift_alerts = [
            item
            for item in alerts.items
            if item.alert_type.value == "critical_feature_drift"
        ]
        assert len(drift_alerts) == 1
        assert drift_alerts[0].occurrence_count == 2

        monitoring.drift_status = DriftSeverity.STABLE
        await service.evaluate(
            registered_model_name="factory_quality",
            version_or_alias="1",
            window_start=START + timedelta(hours=2),
            window_end=NOW + timedelta(hours=2),
            trigger=MonitoringEvaluationTrigger.SCHEDULED,
        )
        resolved = await MonitoringAlertRepository(session).get(drift_alerts[0].id)

    assert resolved is not None
    assert resolved.status is MonitoringAlertStatus.RESOLVED


@pytest.mark.anyio
async def test_missing_reference_and_minimum_sample_statuses_are_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        unavailable = await _service(
            session, FakeMonitoring(missing_reference=True)
        ).evaluate(
            registered_model_name="factory_quality",
            version_or_alias="1",
            window_start=START,
            window_end=NOW,
            trigger=MonitoringEvaluationTrigger.RECONCILIATION,
        )
        insufficient = await _service(session, FakeMonitoring(sample_count=5)).evaluate(
            registered_model_name="factory_quality",
            version_or_alias="1",
            window_start=START + timedelta(days=1),
            window_end=NOW + timedelta(days=1),
            trigger=MonitoringEvaluationTrigger.SCHEDULED,
        )

    assert unavailable.overall_status is MonitoringEvaluationStatus.UNAVAILABLE
    assert unavailable.report["availability"] == {
        "error_code": "missing_reference_profile"
    }
    assert insufficient.overall_status is MonitoringEvaluationStatus.INSUFFICIENT_DATA

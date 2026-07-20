"""Complete exact-version monitoring evaluation and persistence orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.ml.monitoring.alert_service import MonitoringAlertService
from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringEvaluationPage,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
    monitoring_evaluation_idempotency_key,
)
from app.ml.monitoring.exceptions import (
    MonitoringNotFoundError,
    MonitoringPersistenceError,
    MonitoringPreconditionError,
    MonitoringWindowValidationError,
    PredictionMonitoringError,
)
from app.ml.monitoring.models import (
    ClassificationPredictionDrift,
    DataQualitySeverity,
    DriftSeverity,
    FeatureDriftResult,
    ModelDriftReport,
    PredictionDataQualityReport,
    PredictionOperationalSummary,
    RegressionPredictionDrift,
)
from app.ml.monitoring.service import PredictionMonitoringService
from app.ml.registry import BaseModelRegistry, RegisteredModelVersion
from app.ml.registry.exceptions import ModelRegistryError
from app.observability.logging import emit_safe
from app.observability.metrics import (
    record_monitoring_alert_created,
    record_monitoring_alert_resolved,
    record_monitoring_evaluation,
)
from app.observability.tracing import traced_async_operation
from app.repositories.monitoring_evaluations import MonitoringEvaluationRepository
from app.utils.security import utc_now

REPORT_SCHEMA_VERSION = "1.0"
logger = logging.getLogger(__name__)


class MonitoringEvaluationService:
    """Resolve, calculate, persist, alert, and return one bounded evaluation."""

    def __init__(
        self,
        *,
        repository: MonitoringEvaluationRepository,
        monitoring_service: PredictionMonitoringService,
        model_registry: BaseModelRegistry,
        alert_service: MonitoringAlertService,
        minimum_sample_count: int,
        maximum_window_days: int,
        failure_rate_warning_threshold: float,
        failure_rate_critical_threshold: float,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._monitoring = monitoring_service
        self._registry = model_registry
        self._alerts = alert_service
        self._minimum_sample_count = minimum_sample_count
        self._maximum_window_days = maximum_window_days
        self._failure_warning = failure_rate_warning_threshold
        self._failure_critical = failure_rate_critical_threshold
        self._clock = clock

    @traced_async_operation("monitoring.evaluation", attributes={"trigger": "api"})
    async def evaluate(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        window_start: datetime | None,
        window_end: datetime | None,
        trigger: MonitoringEvaluationTrigger,
        idempotency_key: str | None = None,
    ) -> ModelMonitoringEvaluation:
        started_clock = perf_counter()
        try:
            evaluation = await self._evaluate_once(
                registered_model_name=registered_model_name,
                version_or_alias=version_or_alias,
                window_start=window_start,
                window_end=window_end,
                trigger=trigger,
                idempotency_key=idempotency_key,
            )
        except Exception:
            record_monitoring_evaluation(
                trigger=trigger.value,
                final_status="failed",
                duration_seconds=max(perf_counter() - started_clock, 0.0),
            )
            raise
        record_monitoring_evaluation(
            trigger=trigger.value,
            final_status=evaluation.overall_status.value,
            duration_seconds=max(perf_counter() - started_clock, 0.0),
        )
        return evaluation

    async def _evaluate_once(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        window_start: datetime | None,
        window_end: datetime | None,
        trigger: MonitoringEvaluationTrigger,
        idempotency_key: str | None = None,
    ) -> ModelMonitoringEvaluation:
        """Execute the existing idempotent evaluation boundary once."""
        version = self._registry.resolve(registered_model_name, version_or_alias)
        start, end = self._window(window_start, window_end)
        key = idempotency_key or monitoring_evaluation_idempotency_key(
            registered_model_name=registered_model_name,
            model_version=version.version,
            window_start=start,
            window_end=end,
        )
        if not key.strip() or len(key) > 128:
            raise MonitoringWindowValidationError(
                "Monitoring evaluation idempotency key is invalid."
            )
        existing = await self._existing(
            idempotency_key=key,
            registered_model_name=registered_model_name,
            model_version=version.version,
            window_start=start,
            window_end=end,
        )
        if existing is not None:
            return existing

        alias = version_or_alias if not version_or_alias.isdigit() else None
        try:
            await self._monitoring.reference_profile(
                registered_model_name=registered_model_name,
                version_or_alias=version.version,
            )
        except MonitoringNotFoundError:
            evaluation = self._unavailable(
                version=version,
                alias=alias,
                start=start,
                end=end,
                trigger=trigger,
                idempotency_key=key,
                error_code="missing_reference_profile",
            )
        else:
            evaluation = await self._calculate(
                version=version,
                alias=alias,
                start=start,
                end=end,
                trigger=trigger,
                idempotency_key=key,
            )
        return await self._persist(evaluation)

    async def _calculate(
        self,
        *,
        version: RegisteredModelVersion,
        alias: str | None,
        start: datetime,
        end: datetime,
        trigger: MonitoringEvaluationTrigger,
        idempotency_key: str,
    ) -> ModelMonitoringEvaluation:
        try:
            operational = await self._monitoring.operations(
                registered_model_name=version.registered_model_name,
                version_or_alias=version.version,
                start_at=start,
                end_at=end,
                task_type=None,
                status=None,
            )
            quality = await self._monitoring.data_quality(
                registered_model_name=version.registered_model_name,
                version_or_alias=version.version,
                start_at=start,
                end_at=end,
            )
            drift = await self._monitoring.drift(
                registered_model_name=version.registered_model_name,
                version_or_alias=version.version,
                start_at=start,
                end_at=end,
                minimum_sample_count=self._minimum_sample_count,
            )
        except (PredictionMonitoringError, ModelRegistryError):
            return self._unavailable(
                version=version,
                alias=alias,
                start=start,
                end=end,
                trigger=trigger,
                idempotency_key=idempotency_key,
                error_code="monitoring_inputs_unavailable",
            )
        quality_status = _quality_status(quality)
        feature_status = _feature_status(drift.feature_results)
        prediction_status = _drift_status(drift.prediction_result.severity)
        operational_status = self._operational_status(operational)
        component_statuses = (
            quality_status,
            feature_status,
            prediction_status,
            operational_status,
        )
        overall = derive_overall_status(component_statuses)
        now = self._clock()
        return ModelMonitoringEvaluation(
            id=uuid4(),
            registered_model_name=version.registered_model_name,
            model_version=version.version,
            model_alias=alias,
            key=version.key,
            window_start=start,
            window_end=end,
            evaluated_sample_count=drift.current_sample_count,
            successful_prediction_count=operational.success_count,
            failed_prediction_count=operational.failure_count,
            data_quality_status=quality_status,
            feature_drift_status=feature_status,
            prediction_drift_status=prediction_status,
            operational_health_status=operational_status,
            overall_status=overall,
            report_schema_version=REPORT_SCHEMA_VERSION,
            report={
                "availability": {"error_code": None},
                "operational": _operational_payload(operational),
                "data_quality": _quality_payload(quality),
                "drift": _drift_payload(drift),
            },
            warning_count=sum(
                status is MonitoringEvaluationStatus.WARNING
                for status in component_statuses
            ),
            critical_count=sum(
                status is MonitoringEvaluationStatus.CRITICAL
                for status in component_statuses
            ),
            trigger=trigger,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )

    def _unavailable(
        self,
        *,
        version: RegisteredModelVersion,
        alias: str | None,
        start: datetime,
        end: datetime,
        trigger: MonitoringEvaluationTrigger,
        idempotency_key: str,
        error_code: str,
    ) -> ModelMonitoringEvaluation:
        now = self._clock()
        unavailable = MonitoringEvaluationStatus.UNAVAILABLE
        return ModelMonitoringEvaluation(
            id=uuid4(),
            registered_model_name=version.registered_model_name,
            model_version=version.version,
            model_alias=alias,
            key=version.key,
            window_start=start,
            window_end=end,
            evaluated_sample_count=0,
            successful_prediction_count=0,
            failed_prediction_count=0,
            data_quality_status=unavailable,
            feature_drift_status=unavailable,
            prediction_drift_status=unavailable,
            operational_health_status=unavailable,
            overall_status=unavailable,
            report_schema_version=REPORT_SCHEMA_VERSION,
            report={"availability": {"error_code": error_code}},
            warning_count=0,
            critical_count=0,
            trigger=trigger,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )

    async def _persist(
        self, evaluation: ModelMonitoringEvaluation
    ) -> ModelMonitoringEvaluation:
        try:
            persisted = await self._repository.create(evaluation)
            alert_changes = await self._alerts.process_evaluation(persisted)
            await self._repository.commit()
            for alert in alert_changes.created:
                record_monitoring_alert_created(
                    alert_type=alert.alert_type.value,
                    severity=alert.severity.value,
                )
                emit_safe(
                    logger,
                    logging.WARNING,
                    "monitoring_alert_created",
                    extra={
                        "alert_type": alert.alert_type.value,
                        "severity": alert.severity.value,
                        "trigger": evaluation.trigger.value,
                        "lifecycle_status": "created",
                    },
                )
            for alert in alert_changes.resolved:
                record_monitoring_alert_resolved(
                    alert_type=alert.alert_type.value,
                    severity=alert.severity.value,
                )
                emit_safe(
                    logger,
                    logging.INFO,
                    "monitoring_alert_resolved",
                    extra={
                        "alert_type": alert.alert_type.value,
                        "severity": alert.severity.value,
                        "trigger": evaluation.trigger.value,
                        "lifecycle_status": "resolved",
                    },
                )
            return persisted
        except IntegrityError:
            await self._repository.rollback()
            existing = await self._repository.get_by_idempotency(
                evaluation.idempotency_key
            )
            if existing is None:
                existing = await self._repository.get_by_window(
                    registered_model_name=evaluation.registered_model_name,
                    model_version=evaluation.model_version,
                    window_start=evaluation.window_start,
                    window_end=evaluation.window_end,
                )
            if existing is not None:
                return existing
            raise MonitoringPersistenceError(
                "Monitoring evaluation could not be persisted safely."
            ) from None
        except SQLAlchemyError as exc:
            await self._repository.rollback()
            raise MonitoringPersistenceError(
                "Monitoring evaluation storage is unavailable."
            ) from exc
        except MonitoringPersistenceError:
            await self._repository.rollback()
            raise

    async def _existing(
        self,
        *,
        idempotency_key: str,
        registered_model_name: str,
        model_version: str,
        window_start: datetime,
        window_end: datetime,
    ) -> ModelMonitoringEvaluation | None:
        try:
            existing = await self._repository.get_by_idempotency(idempotency_key)
            if existing is not None:
                if (
                    existing.registered_model_name != registered_model_name
                    or existing.model_version != model_version
                    or existing.window_start != window_start
                    or existing.window_end != window_end
                ):
                    raise MonitoringPreconditionError(
                        "The idempotency key already identifies another evaluation."
                    )
                return existing
            return await self._repository.get_by_window(
                registered_model_name=registered_model_name,
                model_version=model_version,
                window_start=window_start,
                window_end=window_end,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Monitoring evaluation storage is unavailable."
            ) from exc

    async def get(self, evaluation_id: UUID) -> ModelMonitoringEvaluation:
        try:
            evaluation = await self._repository.get(evaluation_id)
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Monitoring evaluation storage is unavailable."
            ) from exc
        if evaluation is None:
            raise MonitoringNotFoundError("Monitoring evaluation was not found.")
        return evaluation

    async def latest(
        self, *, registered_model_name: str, model_version: str
    ) -> ModelMonitoringEvaluation:
        if not model_version.isdigit():
            raise MonitoringWindowValidationError("An exact model version is required.")
        try:
            evaluation = await self._repository.latest(
                registered_model_name=registered_model_name,
                model_version=model_version,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Monitoring evaluation storage is unavailable."
            ) from exc
        if evaluation is None:
            raise MonitoringNotFoundError("Monitoring evaluation was not found.")
        return evaluation

    async def list(
        self,
        *,
        registered_model_name: str | None,
        model_version: str | None,
        overall_status: MonitoringEvaluationStatus | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> MonitoringEvaluationPage:
        if (start_at is None) != (end_at is None):
            raise MonitoringWindowValidationError(
                "start_at and end_at must be supplied together."
            )
        if start_at is not None and end_at is not None:
            self._window(start_at, end_at)
        try:
            return await self._repository.list(
                registered_model_name=registered_model_name,
                model_version=model_version,
                overall_status=overall_status,
                start_at=start_at,
                end_at=end_at,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Monitoring evaluation storage is unavailable."
            ) from exc

    def _operational_status(
        self, summary: PredictionOperationalSummary
    ) -> MonitoringEvaluationStatus:
        if summary.request_count == 0:
            return MonitoringEvaluationStatus.INSUFFICIENT_DATA
        if summary.failure_rate >= self._failure_critical:
            return MonitoringEvaluationStatus.CRITICAL
        if summary.failure_rate >= self._failure_warning:
            return MonitoringEvaluationStatus.WARNING
        return MonitoringEvaluationStatus.HEALTHY

    def _window(
        self, start_at: datetime | None, end_at: datetime | None
    ) -> tuple[datetime, datetime]:
        end = _utc(end_at) if end_at is not None else self._clock()
        start = _utc(start_at) if start_at is not None else end - timedelta(hours=24)
        if start >= end:
            raise MonitoringWindowValidationError("start_at must be before end_at.")
        if end - start > timedelta(days=self._maximum_window_days):
            raise MonitoringWindowValidationError(
                "The requested monitoring window exceeds the configured maximum."
            )
        return start, end


def derive_overall_status(
    statuses: tuple[MonitoringEvaluationStatus, ...],
) -> MonitoringEvaluationStatus:
    """Apply a deterministic trust-first aggregate precedence."""
    for status in (
        MonitoringEvaluationStatus.UNAVAILABLE,
        MonitoringEvaluationStatus.CRITICAL,
        MonitoringEvaluationStatus.WARNING,
        MonitoringEvaluationStatus.INSUFFICIENT_DATA,
    ):
        if status in statuses:
            return status
    return MonitoringEvaluationStatus.HEALTHY


def _quality_status(report: PredictionDataQualityReport) -> MonitoringEvaluationStatus:
    severities = {issue.severity for issue in report.issues}
    if DataQualitySeverity.CRITICAL in severities:
        return MonitoringEvaluationStatus.CRITICAL
    if DataQualitySeverity.WARNING in severities:
        return MonitoringEvaluationStatus.WARNING
    return MonitoringEvaluationStatus.HEALTHY


def _feature_status(
    results: tuple[FeatureDriftResult, ...],
) -> MonitoringEvaluationStatus:
    return derive_overall_status(
        tuple(_drift_status(item.severity) for item in results)
    )


def _drift_status(status: DriftSeverity) -> MonitoringEvaluationStatus:
    return {
        DriftSeverity.STABLE: MonitoringEvaluationStatus.HEALTHY,
        DriftSeverity.WARNING: MonitoringEvaluationStatus.WARNING,
        DriftSeverity.CRITICAL: MonitoringEvaluationStatus.CRITICAL,
        DriftSeverity.INSUFFICIENT_DATA: MonitoringEvaluationStatus.INSUFFICIENT_DATA,
    }[status]


def _operational_payload(value: PredictionOperationalSummary) -> dict[str, object]:
    return {
        "request_count": value.request_count,
        "success_count": value.success_count,
        "failure_count": value.failure_count,
        "success_rate": value.success_rate,
        "failure_rate": value.failure_rate,
        "average_latency_ms": value.average_latency_ms,
        "minimum_latency_ms": value.minimum_latency_ms,
        "maximum_latency_ms": value.maximum_latency_ms,
        "p50_latency_ms": value.p50_latency_ms,
        "p95_latency_ms": value.p95_latency_ms,
        "p99_latency_ms": value.p99_latency_ms,
        "total_predicted_rows": value.total_predicted_rows,
        "average_batch_size": value.average_batch_size,
        "failures_by_error_code": dict(value.failures_by_error_code),
        "matched_event_count": value.matched_event_count,
        "analyzed_event_count": value.analyzed_event_count,
        "truncated": value.truncated,
        "analysis_warning": value.analysis_warning,
        "instance_capture_failures_since_start": (
            value.instance_capture_failures_since_start
        ),
    }


def _quality_payload(value: PredictionDataQualityReport) -> dict[str, object]:
    return {
        "request_count": value.request_count,
        "row_count": value.row_count,
        "missing_value_count": value.missing_value_count,
        "non_finite_value_count": value.non_finite_value_count,
        "feature_count_mismatch_requests": value.feature_count_mismatch_requests,
        "empty_batch_requests": value.empty_batch_requests,
        "constant_column_occurrences": value.constant_column_occurrences,
        "out_of_reference_range_count": value.out_of_reference_range_count,
        "finite_value_count": value.finite_value_count,
        "out_of_reference_range_proportion": value.out_of_reference_range_proportion,
        "issues": [
            {
                "code": item.code,
                "severity": item.severity.value,
                "count": item.count,
                "proportion": item.proportion,
            }
            for item in value.issues
        ],
        "matched_event_count": value.matched_event_count,
        "analyzed_event_count": value.analyzed_event_count,
        "truncated": value.truncated,
        "analysis_warning": value.analysis_warning,
    }


def _drift_payload(value: ModelDriftReport) -> dict[str, object]:
    prediction = value.prediction_result
    prediction_payload: dict[str, object] = {
        "reference_sample_count": prediction.reference_sample_count,
        "current_sample_count": prediction.current_sample_count,
        "severity": prediction.severity.value,
    }
    if isinstance(prediction, RegressionPredictionDrift):
        prediction_payload.update(
            psi=prediction.psi,
            mean_shift=prediction.mean_shift,
            standard_deviation_ratio=prediction.standard_deviation_ratio,
        )
    elif isinstance(prediction, ClassificationPredictionDrift):
        prediction_payload["total_variation_distance"] = (
            prediction.total_variation_distance
        )
    return {
        "reference_sample_count": value.reference_sample_count,
        "current_sample_count": value.current_sample_count,
        "feature_results": [
            {
                "feature_index": item.feature_index,
                "psi": item.psi,
                "reference_sample_count": item.reference_sample_count,
                "current_sample_count": item.current_sample_count,
                "missing_rate_difference": item.missing_rate_difference,
                "out_of_reference_range_proportion": (
                    item.out_of_reference_range_proportion
                ),
                "severity": item.severity.value,
            }
            for item in value.feature_results
        ],
        "prediction_result": prediction_payload,
        "aggregate_status": value.aggregate_status.value,
        "thresholds": {
            "warning": value.thresholds.warning,
            "critical": value.thresholds.critical,
            "missing_rate_warning": value.thresholds.missing_rate_warning,
            "out_of_range_warning": value.thresholds.out_of_range_warning,
            "epsilon": value.thresholds.epsilon,
        },
        "generated_at": value.generated_at.isoformat(),
        "matched_event_count": value.matched_event_count,
        "analyzed_event_count": value.analyzed_event_count,
        "truncated": value.truncated,
        "analysis_warning": value.analysis_warning,
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonitoringWindowValidationError(
            "Monitoring timestamps must include a UTC offset."
        )
    return value.astimezone(UTC)

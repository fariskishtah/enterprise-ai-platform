"""Application services for bounded prediction monitoring and drift reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.ml.domain import TaskType
from app.ml.monitoring.capture import PredictionCaptureHealth
from app.ml.monitoring.drift import DriftDetectionEngine
from app.ml.monitoring.exceptions import (
    MonitoringNotFoundError,
    MonitoringPersistenceError,
    MonitoringPreconditionError,
    MonitoringWindowValidationError,
)
from app.ml.monitoring.models import (
    DataQualityIssue,
    DataQualitySeverity,
    DriftThresholds,
    ModelDriftReport,
    ModelReferenceProfile,
    PredictionDataQualityReport,
    PredictionEvent,
    PredictionEventPage,
    PredictionEventStatus,
    PredictionOperationalSummary,
)
from app.ml.registry import BaseModelRegistry, RegisteredModelVersion
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.utils.security import utc_now


@dataclass(frozen=True, slots=True)
class MonitoringWindow:
    """Validated bounded UTC monitoring interval."""

    start_at: datetime
    end_at: datetime


@dataclass(frozen=True, slots=True)
class _ReportInputs:
    """Exact version, profile, window, and newest bounded event selection."""

    version: RegisteredModelVersion
    reference: ModelReferenceProfile
    window: MonitoringWindow
    events: tuple[PredictionEvent, ...]
    matched_event_count: int

    @property
    def analyzed_event_count(self) -> int:
        return len(self.events)

    @property
    def truncated(self) -> bool:
        return self.matched_event_count > self.analyzed_event_count


_OPERATIONAL_PARTIAL_WARNING = (
    "Latency percentiles use only the newest matching events within the configured "
    "analysis limit; database-backed totals cover the complete requested window."
)
_REPORT_PARTIAL_WARNING = (
    "Analysis uses only the newest matching events within the configured analysis "
    "limit, so it represents a partial requested window."
)


class PredictionMonitoringService:
    """Resolve exact versions and coordinate typed monitoring calculations."""

    def __init__(
        self,
        *,
        repository: PredictionMonitoringRepository,
        model_registry: BaseModelRegistry,
        drift_engine: DriftDetectionEngine,
        capture_health: PredictionCaptureHealth,
        minimum_sample_count: int,
        maximum_window_days: int,
        maximum_events_per_window: int,
        thresholds: DriftThresholds,
    ) -> None:
        self._repository = repository
        self._model_registry = model_registry
        self._drift_engine = drift_engine
        self._capture_health = capture_health
        self._minimum_sample_count = minimum_sample_count
        self._maximum_window_days = maximum_window_days
        self._maximum_events_per_window = maximum_events_per_window
        self._thresholds = thresholds

    async def get_event(self, event_id: UUID) -> PredictionEvent:
        """Return a safe event summary or an authorization-neutral absence."""
        try:
            event = await self._repository.get_event(event_id)
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Prediction monitoring storage is unavailable.",
            ) from exc
        if event is None:
            raise MonitoringNotFoundError("Prediction event was not found.")
        return event

    async def list_events(
        self,
        *,
        registered_model_name: str | None,
        resolved_model_version: str | None,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> PredictionEventPage:
        """Return one bounded event page using optional safe filters."""
        if (start_at is None) != (end_at is None):
            raise MonitoringWindowValidationError(
                "start_at and end_at must be supplied together.",
            )
        if start_at is not None and end_at is not None:
            self._window(start_at, end_at)
        try:
            return await self._repository.list_events(
                registered_model_name=registered_model_name,
                resolved_model_version=resolved_model_version,
                task_type=task_type,
                status=status,
                start_at=start_at,
                end_at=end_at,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Prediction monitoring storage is unavailable.",
            ) from exc

    async def operations(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        start_at: datetime | None,
        end_at: datetime | None,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
    ) -> PredictionOperationalSummary:
        """Aggregate request outcomes, latency, rows, batches, and safe errors."""
        version = self._resolve(registered_model_name, version_or_alias)
        window = self._window(start_at, end_at)
        try:
            aggregate = await self._repository.aggregate_operations(
                registered_model_name=registered_model_name,
                resolved_model_version=version.version,
                task_type=task_type,
                status=status,
                start_at=window.start_at,
                end_at=window.end_at,
            )
            durations = await self._repository.list_durations(
                registered_model_name=registered_model_name,
                resolved_model_version=version.version,
                task_type=task_type,
                status=status,
                start_at=window.start_at,
                end_at=window.end_at,
                limit=self._maximum_events_per_window,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Prediction monitoring storage is unavailable.",
            ) from exc
        count = aggregate.request_count
        analyzed_count = len(durations)
        truncated = count > analyzed_count
        return PredictionOperationalSummary(
            registered_model_name=registered_model_name,
            model_version=version.version,
            start_at=window.start_at,
            end_at=window.end_at,
            request_count=count,
            success_count=aggregate.success_count,
            failure_count=aggregate.failure_count,
            success_rate=aggregate.success_count / count if count else 0.0,
            failure_rate=aggregate.failure_count / count if count else 0.0,
            average_latency_ms=(aggregate.duration_total_ms / count if count else None),
            minimum_latency_ms=aggregate.minimum_duration_ms,
            maximum_latency_ms=aggregate.maximum_duration_ms,
            p50_latency_ms=calculate_percentile(durations, 0.50),
            p95_latency_ms=calculate_percentile(durations, 0.95),
            p99_latency_ms=calculate_percentile(durations, 0.99),
            total_predicted_rows=aggregate.total_predicted_rows,
            average_batch_size=(
                aggregate.total_predicted_rows / count if count else None
            ),
            failures_by_error_code=aggregate.failures_by_error_code,
            matched_event_count=count,
            analyzed_event_count=analyzed_count,
            truncated=truncated,
            analysis_warning=_OPERATIONAL_PARTIAL_WARNING if truncated else None,
            instance_capture_failures_since_start=(
                self._capture_health.snapshot().instance_capture_failures_since_start
            ),
        )

    async def data_quality(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> PredictionDataQualityReport:
        """Aggregate invalid-shape signals separately from unusual distributions."""
        inputs = await self._report_inputs(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
            start_at=start_at,
            end_at=end_at,
        )
        version = inputs.version
        reference = inputs.reference
        window = inputs.window
        events = inputs.events
        request_count = len(events)
        row_count = sum(event.row_count for event in events)
        missing_count = sum(
            feature.summary.missing_count
            for event in events
            for feature in event.feature_profile
        )
        non_finite_count = sum(
            feature.summary.non_finite_count
            for event in events
            for feature in event.feature_profile
        )
        finite_count = sum(
            feature.summary.finite_count
            for event in events
            for feature in event.feature_profile
        )
        mismatches = sum(
            event.feature_count != reference.feature_count for event in events
        )
        empty_batches = sum(event.row_count == 0 for event in events)
        constant_columns = sum(
            feature.summary.finite_count > 0
            and feature.summary.minimum == feature.summary.maximum
            for event in events
            for feature in event.feature_profile
        )
        out_of_range = sum(
            feature.out_of_reference_range_count
            for event in events
            for feature in event.feature_profile
        )
        out_of_range_proportion = out_of_range / finite_count if finite_count else 0.0
        issues: list[DataQualityIssue] = []
        if mismatches:
            issues.append(
                DataQualityIssue(
                    "feature_count_mismatch",
                    DataQualitySeverity.CRITICAL,
                    mismatches,
                    mismatches / request_count if request_count else 0.0,
                ),
            )
        if empty_batches:
            issues.append(
                DataQualityIssue(
                    "empty_batch",
                    DataQualitySeverity.CRITICAL,
                    empty_batches,
                    empty_batches / request_count if request_count else 0.0,
                ),
            )
        if missing_count:
            issues.append(
                DataQualityIssue(
                    "missing_values",
                    DataQualitySeverity.CRITICAL,
                    missing_count,
                    missing_count / (finite_count + non_finite_count),
                ),
            )
        if non_finite_count:
            issues.append(
                DataQualityIssue(
                    "non_finite_values",
                    DataQualitySeverity.CRITICAL,
                    non_finite_count,
                    non_finite_count / (finite_count + non_finite_count),
                ),
            )
        if constant_columns:
            total_columns = sum(len(event.feature_profile) for event in events)
            issues.append(
                DataQualityIssue(
                    "constant_columns_within_request",
                    DataQualitySeverity.WARNING,
                    constant_columns,
                    constant_columns / total_columns if total_columns else 0.0,
                ),
            )
        if out_of_range_proportion >= self._thresholds.out_of_range_warning and (
            finite_count > 0
        ):
            issues.append(
                DataQualityIssue(
                    "out_of_reference_range",
                    DataQualitySeverity.WARNING,
                    out_of_range,
                    out_of_range_proportion,
                ),
            )
        return PredictionDataQualityReport(
            registered_model_name=registered_model_name,
            model_version=version.version,
            start_at=window.start_at,
            end_at=window.end_at,
            request_count=request_count,
            row_count=row_count,
            missing_value_count=missing_count,
            non_finite_value_count=non_finite_count,
            feature_count_mismatch_requests=mismatches,
            empty_batch_requests=empty_batches,
            constant_column_occurrences=constant_columns,
            out_of_reference_range_count=out_of_range,
            finite_value_count=finite_count,
            out_of_reference_range_proportion=out_of_range_proportion,
            issues=tuple(issues),
            matched_event_count=inputs.matched_event_count,
            analyzed_event_count=inputs.analyzed_event_count,
            truncated=inputs.truncated,
            analysis_warning=_REPORT_PARTIAL_WARNING if inputs.truncated else None,
        )

    async def drift(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        start_at: datetime | None,
        end_at: datetime | None,
        minimum_sample_count: int | None,
    ) -> ModelDriftReport:
        """Generate pure drift results against one exact-version reference."""
        inputs = await self._report_inputs(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
            start_at=start_at,
            end_at=end_at,
        )
        version = inputs.version
        reference = inputs.reference
        window = inputs.window
        minimum = minimum_sample_count or self._minimum_sample_count
        if minimum <= 0 or minimum > self._maximum_events_per_window:
            raise MonitoringWindowValidationError(
                "minimum_sample_count is outside the configured safe range.",
            )
        if version.key != reference.key:
            raise MonitoringPreconditionError(
                "Reference profile trainer identity does not match the model version.",
            )
        return self._drift_engine.detect(
            reference=reference,
            events=inputs.events,
            start_at=window.start_at,
            end_at=window.end_at,
            minimum_sample_count=minimum,
            thresholds=self._thresholds,
            generated_at=utc_now(),
            matched_event_count=inputs.matched_event_count,
        )

    async def reference_profile(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
    ) -> ModelReferenceProfile:
        """Resolve an alias once and return its exact-version profile."""
        version = self._resolve(registered_model_name, version_or_alias)
        try:
            profile = await self._repository.get_reference_profile(
                registered_model_name,
                version.version,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Prediction monitoring storage is unavailable.",
            ) from exc
        if profile is None:
            raise MonitoringNotFoundError(
                "A reference profile is not available for this model version.",
            )
        return profile

    async def _report_inputs(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> _ReportInputs:
        version = self._resolve(registered_model_name, version_or_alias)
        window = self._window(start_at, end_at)
        try:
            reference = await self._repository.get_reference_profile(
                registered_model_name,
                version.version,
            )
            page = await self._repository.list_window_events(
                registered_model_name=registered_model_name,
                resolved_model_version=version.version,
                start_at=window.start_at,
                end_at=window.end_at,
                limit=self._maximum_events_per_window,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Prediction monitoring storage is unavailable.",
            ) from exc
        if reference is None:
            raise MonitoringNotFoundError(
                "A reference profile is not available for this model version.",
            )
        return _ReportInputs(
            version=version,
            reference=reference,
            window=window,
            events=page.items,
            matched_event_count=page.total,
        )

    def _resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        return self._model_registry.resolve(
            registered_model_name,
            version_or_alias,
        )

    def _window(
        self,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> MonitoringWindow:
        resolved_end = _utc(end_at) if end_at is not None else utc_now()
        resolved_start = (
            _utc(start_at)
            if start_at is not None
            else resolved_end - timedelta(hours=24)
        )
        if resolved_start >= resolved_end:
            raise MonitoringWindowValidationError("start_at must be before end_at.")
        if resolved_end - resolved_start > timedelta(days=self._maximum_window_days):
            raise MonitoringWindowValidationError(
                "The requested monitoring window exceeds the configured maximum.",
            )
        return MonitoringWindow(resolved_start, resolved_end)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonitoringWindowValidationError(
            "Monitoring timestamps must include a UTC offset.",
        )
    return value.astimezone(UTC)


def calculate_percentile(
    values: tuple[float, ...],
    proportion: float,
) -> float | None:
    """Linearly interpolate a deterministic percentile from sorted values."""
    if not values:
        return None
    position = (len(values) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] + (values[upper] - values[lower]) * weight

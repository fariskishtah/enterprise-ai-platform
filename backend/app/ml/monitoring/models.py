"""Immutable prediction-monitoring, reference-profile, and drift contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from app.ml.base import TrainerKey

MAX_PERSISTED_CLASS_LABELS = 100


class PredictionEventStatus(StrEnum):
    """Terminal states for one completed prediction API attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReferenceProfileSource(StrEnum):
    """Trusted data source used to construct a model-version profile."""

    EVALUATION = "evaluation"


class DriftSeverity(StrEnum):
    """Operational interpretation of a configured drift threshold."""

    STABLE = "stable"
    WARNING = "warning"
    CRITICAL = "critical"
    INSUFFICIENT_DATA = "insufficient_data"


class DataQualitySeverity(StrEnum):
    """Severity for an aggregated request-profile quality issue."""

    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class NumericSummary:
    """Privacy-preserving numeric aggregates without source observations."""

    count: int
    missing_count: int
    finite_count: int
    minimum: float | None
    maximum: float | None
    mean: float | None
    standard_deviation: float | None
    quantiles: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate count relationships and detach the quantile mapping."""
        if self.count < 0 or self.missing_count < 0 or self.finite_count < 0:
            raise ValueError("Numeric summary counts must be non-negative.")
        if self.missing_count > self.count or self.finite_count > self.count:
            raise ValueError("Numeric summary component counts exceed count.")
        if self.minimum is None:
            if (
                any(
                    value is not None
                    for value in (
                        self.maximum,
                        self.mean,
                        self.standard_deviation,
                    )
                )
                or self.quantiles
            ):
                raise ValueError("Empty numeric summaries cannot contain statistics.")
        else:
            maximum = self.maximum
            mean = self.mean
            standard_deviation = self.standard_deviation
            if maximum is None or mean is None or standard_deviation is None:
                raise ValueError("Numeric summary statistics must be complete.")
            values = (
                self.minimum,
                maximum,
                mean,
                standard_deviation,
                *self.quantiles.values(),
            )
            if self.finite_count == 0 or not all(
                math.isfinite(value) for value in values
            ):
                raise ValueError("Numeric summary statistics must be finite.")
            if self.minimum > maximum:
                raise ValueError("Numeric summary bounds are invalid.")
            if standard_deviation < 0:
                raise ValueError("Numeric standard deviation must be non-negative.")
        object.__setattr__(self, "quantiles", MappingProxyType(dict(self.quantiles)))

    @property
    def non_finite_count(self) -> int:
        """Return all NaN and infinite observations."""
        return self.count - self.finite_count


@dataclass(frozen=True, slots=True)
class FeatureRequestProfile:
    """One feature's per-request summary and optional reference-bin counts."""

    feature_index: int
    summary: NumericSummary
    reference_bin_counts: tuple[int, ...] | None
    out_of_reference_range_count: int

    def __post_init__(self) -> None:
        """Protect bounded, non-negative request-profile fields."""
        if self.feature_index < 0 or self.out_of_reference_range_count < 0:
            raise ValueError("Feature profile counts and index must be non-negative.")
        if self.out_of_reference_range_count > self.summary.finite_count:
            raise ValueError("Out-of-range count exceeds the finite feature count.")
        if self.reference_bin_counts is not None:
            if not self.reference_bin_counts or any(
                count < 0 for count in self.reference_bin_counts
            ):
                raise ValueError(
                    "Reference-bin counts must be non-empty and non-negative."
                )
            if sum(self.reference_bin_counts) != self.summary.finite_count:
                raise ValueError("Reference-bin counts must cover all finite values.")


@dataclass(frozen=True, slots=True)
class RegressionPredictionProfile:
    """Regression prediction aggregates and optional fixed-bin counts."""

    summary: NumericSummary
    reference_bin_counts: tuple[int, ...] | None

    def __post_init__(self) -> None:
        """Require histogram counts to cover the finite predictions."""
        if self.reference_bin_counts is not None and (
            not self.reference_bin_counts
            or any(count < 0 for count in self.reference_bin_counts)
            or sum(self.reference_bin_counts) != self.summary.finite_count
        ):
            raise ValueError("Prediction-bin counts must cover all finite values.")


@dataclass(frozen=True, slots=True)
class ClassificationPredictionProfile:
    """Bounded predicted-label frequencies without raw prediction rows."""

    count: int
    class_counts: Mapping[str, int]
    other_count: int = 0

    def __post_init__(self) -> None:
        """Validate and detach bounded class-frequency data."""
        copied = dict(self.class_counts)
        if self.count < 0 or self.other_count < 0:
            raise ValueError("Classification counts must be non-negative.")
        if len(copied) > MAX_PERSISTED_CLASS_LABELS:
            raise ValueError("Classification profile contains too many labels.")
        if any(not label or count < 0 for label, count in copied.items()):
            raise ValueError("Classification label counts are invalid.")
        if sum(copied.values()) + self.other_count != self.count:
            raise ValueError("Classification label counts must sum to count.")
        object.__setattr__(self, "class_counts", MappingProxyType(copied))


type PredictionRequestProfile = (
    RegressionPredictionProfile | ClassificationPredictionProfile
)


@dataclass(frozen=True, slots=True)
class PredictionEvent:
    """One completed authenticated prediction attempt and safe summaries."""

    id: UUID
    requested_by_user_id: UUID
    registered_model_name: str
    requested_model_reference: str
    resolved_model_version: str | None
    resolved_aliases: tuple[str, ...]
    key: TrainerKey
    status: PredictionEventStatus
    row_count: int
    feature_count: int
    duration_ms: float
    feature_profile: tuple[FeatureRequestProfile, ...]
    prediction_profile: PredictionRequestProfile | None
    error_code: str | None
    safe_error_message: str | None
    correlation_id: str | None
    created_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        """Enforce terminal event consistency without retaining raw input."""
        if not self.registered_model_name or not self.requested_model_reference:
            raise ValueError("Prediction model references must be non-empty.")
        if self.row_count < 0 or self.feature_count < 0 or self.duration_ms < 0:
            raise ValueError(
                "Prediction event dimensions and duration are non-negative."
            )
        if self.completed_at < self.created_at:
            raise ValueError("Prediction completion cannot precede its start.")
        if len(self.feature_profile) != self.feature_count:
            raise ValueError("Feature profile count must match feature_count.")
        if self.status is PredictionEventStatus.SUCCEEDED:
            if (
                self.row_count == 0
                or self.resolved_model_version is None
                or self.prediction_profile is None
                or self.error_code is not None
                or self.safe_error_message is not None
            ):
                raise ValueError("Successful prediction event fields are inconsistent.")
        elif self.prediction_profile is not None:
            raise ValueError("Failed prediction events cannot contain predictions.")
        if (self.error_code is None) != (self.safe_error_message is None):
            raise ValueError("Failure code and safe message must be supplied together.")


@dataclass(frozen=True, slots=True)
class NumericReferenceProfile:
    """Immutable reference statistics and deterministic finite bin boundaries."""

    summary: NumericSummary
    bin_edges: tuple[float, ...]
    bin_counts: tuple[int, ...]

    def __post_init__(self) -> None:
        """Validate ordered edges and matching reference counts."""
        if any(not math.isfinite(edge) for edge in self.bin_edges):
            raise ValueError("Reference bin edges must be finite.")
        if tuple(sorted(set(self.bin_edges))) != self.bin_edges:
            raise ValueError("Reference bin edges must be strictly increasing.")
        if len(self.bin_counts) != len(self.bin_edges) + 1:
            raise ValueError("Reference histogram size does not match its edges.")
        if any(count < 0 for count in self.bin_counts):
            raise ValueError("Reference bin counts must be non-negative.")
        if sum(self.bin_counts) != self.summary.finite_count:
            raise ValueError("Reference bins must cover all finite observations.")


@dataclass(frozen=True, slots=True)
class FeatureReferenceProfile:
    """Reference distribution for one stable feature-column index."""

    feature_index: int
    profile: NumericReferenceProfile

    def __post_init__(self) -> None:
        if self.feature_index < 0:
            raise ValueError("Feature index must be non-negative.")


@dataclass(frozen=True, slots=True)
class RegressionPredictionReferenceProfile:
    """Reference distribution for scalar regression predictions."""

    profile: NumericReferenceProfile


@dataclass(frozen=True, slots=True)
class ClassificationPredictionReferenceProfile:
    """Reference predicted-label distribution with a bounded label vocabulary."""

    profile: ClassificationPredictionProfile


type PredictionReferenceProfile = (
    RegressionPredictionReferenceProfile | ClassificationPredictionReferenceProfile
)


@dataclass(frozen=True, slots=True)
class ModelReferenceProfile:
    """Version-owned immutable profile built from held-out evaluation data."""

    id: UUID
    registered_model_name: str
    model_version: str
    key: TrainerKey
    source: ReferenceProfileSource
    feature_count: int
    features: tuple[FeatureReferenceProfile, ...]
    prediction: PredictionReferenceProfile
    sample_count: int
    training_job_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.registered_model_name or not self.model_version:
            raise ValueError("Reference profile model identity must be non-empty.")
        if self.sample_count <= 0 or self.feature_count <= 0:
            raise ValueError("Reference profiles require positive dimensions.")
        if len(self.features) != self.feature_count:
            raise ValueError("Reference feature profiles must match feature_count.")
        if any(
            feature.feature_index != index
            for index, feature in enumerate(self.features)
        ):
            raise ValueError("Reference feature indexes must be contiguous.")


@dataclass(frozen=True, slots=True)
class ModelReferenceProfileDraft:
    """Fully summarized profile awaiting its training-job persistence identity."""

    registered_model_name: str
    model_version: str
    key: TrainerKey
    source: ReferenceProfileSource
    feature_count: int
    features: tuple[FeatureReferenceProfile, ...]
    prediction: PredictionReferenceProfile
    sample_count: int
    created_at: datetime

    def finalize(
        self, *, profile_id: UUID, training_job_id: UUID
    ) -> ModelReferenceProfile:
        """Attach durable identifiers without changing summarized distributions."""
        return ModelReferenceProfile(
            id=profile_id,
            registered_model_name=self.registered_model_name,
            model_version=self.model_version,
            key=self.key,
            source=self.source,
            feature_count=self.feature_count,
            features=self.features,
            prediction=self.prediction,
            sample_count=self.sample_count,
            training_job_id=training_job_id,
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class PredictionEventPage:
    """Paginated safe prediction-event records."""

    items: tuple[PredictionEvent, ...]
    total: int


@dataclass(frozen=True, slots=True)
class OperationalAggregate:
    """Database-calculated operational totals before percentile enrichment."""

    request_count: int
    success_count: int
    failure_count: int
    duration_total_ms: float
    minimum_duration_ms: float | None
    maximum_duration_ms: float | None
    total_predicted_rows: int
    failures_by_error_code: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "failures_by_error_code",
            MappingProxyType(dict(self.failures_by_error_code)),
        )


@dataclass(frozen=True, slots=True)
class PredictionOperationalSummary:
    """Window totals plus bounded newest-event latency percentile coverage."""

    registered_model_name: str
    model_version: str
    start_at: datetime
    end_at: datetime
    request_count: int
    success_count: int
    failure_count: int
    success_rate: float
    failure_rate: float
    average_latency_ms: float | None
    minimum_latency_ms: float | None
    maximum_latency_ms: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    total_predicted_rows: int
    average_batch_size: float | None
    failures_by_error_code: Mapping[str, int]
    matched_event_count: int
    analyzed_event_count: int
    truncated: bool
    analysis_warning: str | None
    instance_capture_failures_since_start: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "failures_by_error_code",
            MappingProxyType(dict(self.failures_by_error_code)),
        )


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    """One explicit aggregate quality observation."""

    code: str
    severity: DataQualitySeverity
    count: int
    proportion: float


@dataclass(frozen=True, slots=True)
class PredictionDataQualityReport:
    """Newest-event request quality with explicit partial-window coverage."""

    registered_model_name: str
    model_version: str
    start_at: datetime
    end_at: datetime
    request_count: int
    row_count: int
    missing_value_count: int
    non_finite_value_count: int
    feature_count_mismatch_requests: int
    empty_batch_requests: int
    constant_column_occurrences: int
    out_of_reference_range_count: int
    finite_value_count: int
    out_of_reference_range_proportion: float
    issues: tuple[DataQualityIssue, ...]
    matched_event_count: int
    analyzed_event_count: int
    truncated: bool
    analysis_warning: str | None


@dataclass(frozen=True, slots=True)
class DriftThresholds:
    """Configured operational defaults used for one generated report."""

    warning: float
    critical: float
    missing_rate_warning: float
    out_of_range_warning: float
    epsilon: float = 1e-6

    def __post_init__(self) -> None:
        values = (
            self.warning,
            self.critical,
            self.missing_rate_warning,
            self.out_of_range_warning,
            self.epsilon,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Drift thresholds must be finite.")
        if not 0 <= self.warning < self.critical:
            raise ValueError("Drift warning threshold must be below critical.")
        if not 0 <= self.missing_rate_warning <= 1:
            raise ValueError("Missing-rate warning threshold must be within [0, 1].")
        if not 0 <= self.out_of_range_warning <= 1:
            raise ValueError("Out-of-range threshold must be within [0, 1].")
        if self.epsilon <= 0:
            raise ValueError("Drift smoothing epsilon must be positive.")


@dataclass(frozen=True, slots=True)
class FeatureDriftResult:
    """PSI and quality shifts for one feature index."""

    feature_index: int
    psi: float | None
    reference_sample_count: int
    current_sample_count: int
    missing_rate_difference: float | None
    out_of_reference_range_proportion: float | None
    severity: DriftSeverity


@dataclass(frozen=True, slots=True)
class RegressionPredictionDrift:
    """Regression output PSI and moment shifts."""

    psi: float | None
    mean_shift: float | None
    standard_deviation_ratio: float | None
    reference_sample_count: int
    current_sample_count: int
    severity: DriftSeverity


@dataclass(frozen=True, slots=True)
class ClassificationPredictionDrift:
    """Predicted-label total variation for classification output."""

    total_variation_distance: float | None
    reference_sample_count: int
    current_sample_count: int
    severity: DriftSeverity


type PredictionDrift = RegressionPredictionDrift | ClassificationPredictionDrift


@dataclass(frozen=True, slots=True)
class ModelDriftReport:
    """Exact-version drift with explicit newest-event analysis coverage."""

    registered_model_name: str
    model_version: str
    key: TrainerKey
    reference_source: ReferenceProfileSource
    reference_sample_count: int
    current_sample_count: int
    start_at: datetime
    end_at: datetime
    feature_results: tuple[FeatureDriftResult, ...]
    prediction_result: PredictionDrift
    aggregate_status: DriftSeverity
    thresholds: DriftThresholds
    generated_at: datetime
    matched_event_count: int
    analyzed_event_count: int
    truncated: bool
    analysis_warning: str | None

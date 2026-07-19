"""Typed transport schemas for prediction monitoring and drift APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ml.monitoring import (
    DataQualitySeverity,
    DriftSeverity,
    PredictionEventStatus,
    ReferenceProfileSource,
)
from app.schemas.ai import TrainerKeyResponse


class NumericSummaryResponse(BaseModel):
    """Privacy-preserving numeric statistics without raw observations."""

    model_config = ConfigDict(frozen=True)

    count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    finite_count: int = Field(ge=0)
    non_finite_count: int = Field(ge=0)
    minimum: float | None
    maximum: float | None
    mean: float | None
    standard_deviation: float | None
    quantiles: dict[str, float]


class FeatureRequestProfileResponse(BaseModel):
    """One request feature's safe aggregates and optional fixed-bin counts."""

    model_config = ConfigDict(frozen=True)

    feature_index: int = Field(ge=0)
    summary: NumericSummaryResponse
    reference_bin_counts: tuple[int, ...] | None
    out_of_reference_range_count: int = Field(ge=0)


class RegressionPredictionProfileResponse(BaseModel):
    """Safe regression output aggregates."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["regression"] = "regression"
    summary: NumericSummaryResponse
    reference_bin_counts: tuple[int, ...] | None


class ClassificationPredictionProfileResponse(BaseModel):
    """Bounded predicted-label frequencies; no class probabilities are implied."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["classification"] = "classification"
    count: int = Field(ge=0)
    class_counts: dict[str, int]
    other_count: int = Field(ge=0)


PredictionProfileResponse = Annotated[
    RegressionPredictionProfileResponse | ClassificationPredictionProfileResponse,
    Field(discriminator="kind"),
]


class PredictionEventResponse(BaseModel):
    """Safe completed-event response with no requester or raw matrix."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(
        examples=["3f9655cb-8778-45e9-81e8-4566286200fb"],
    )
    registered_model_name: str = Field(
        examples=["ai_core_random_forest_regression"],
    )
    requested_model_reference: str = Field(examples=["champion"])
    resolved_model_version: str | None = Field(default=None, examples=["7"])
    resolved_aliases: tuple[str, ...]
    trainer_key: TrainerKeyResponse
    status: PredictionEventStatus = Field(examples=["succeeded"])
    row_count: int = Field(ge=0)
    feature_count: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    feature_profile: tuple[FeatureRequestProfileResponse, ...]
    prediction_profile: PredictionProfileResponse | None
    error_code: str | None
    safe_error_message: str | None
    correlation_id: str | None
    created_at: datetime
    completed_at: datetime


class PredictionEventPageResponse(BaseModel):
    """Bounded prediction-event page."""

    model_config = ConfigDict(frozen=True)

    items: tuple[PredictionEventResponse, ...]
    total: int = Field(ge=0)
    limit: int = Field(gt=0)
    offset: int = Field(ge=0)


class PredictionOperationalSummaryResponse(BaseModel):
    """Full-window totals with explicitly bounded newest-event percentiles."""

    model_config = ConfigDict(frozen=True)

    registered_model_name: str = Field(
        examples=["ai_core_random_forest_regression"],
    )
    model_version: str = Field(examples=["7"])
    start_at: datetime
    end_at: datetime
    request_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    failure_rate: float = Field(ge=0, le=1)
    average_latency_ms: float | None = Field(default=None, ge=0)
    minimum_latency_ms: float | None = Field(default=None, ge=0)
    maximum_latency_ms: float | None = Field(default=None, ge=0)
    p50_latency_ms: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    p99_latency_ms: float | None = Field(default=None, ge=0)
    total_predicted_rows: int = Field(ge=0)
    average_batch_size: float | None = Field(default=None, ge=0)
    failures_by_error_code: dict[str, int]
    matched_event_count: int = Field(
        ge=0,
        description="All database events matching the requested window and filters.",
    )
    analyzed_event_count: int = Field(
        ge=0,
        description="Newest matching events used for latency percentiles.",
    )
    truncated: bool = Field(
        description="Whether latency percentiles use a partial newest-event set.",
    )
    analysis_warning: str | None
    instance_capture_failures_since_start: int = Field(
        ge=0,
        description=(
            "Capture persistence failures in only the API process serving this "
            "request. Resets on restart; is not window-filtered, replica-aggregated, "
            "or durable."
        ),
    )


class DataQualityIssueResponse(BaseModel):
    """One aggregated data-quality issue."""

    model_config = ConfigDict(frozen=True)

    code: str
    severity: DataQualitySeverity
    count: int = Field(ge=0)
    proportion: float = Field(ge=0, le=1)


class PredictionDataQualityResponse(BaseModel):
    """Newest-event request quality with explicit partial-window coverage."""

    model_config = ConfigDict(frozen=True)

    registered_model_name: str = Field(
        examples=["ai_core_random_forest_regression"],
    )
    model_version: str = Field(examples=["7"])
    start_at: datetime
    end_at: datetime
    request_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    missing_value_count: int = Field(ge=0)
    non_finite_value_count: int = Field(ge=0)
    feature_count_mismatch_requests: int = Field(ge=0)
    empty_batch_requests: int = Field(ge=0)
    constant_column_occurrences: int = Field(ge=0)
    out_of_reference_range_count: int = Field(ge=0)
    finite_value_count: int = Field(ge=0)
    out_of_reference_range_proportion: float = Field(ge=0, le=1)
    issues: tuple[DataQualityIssueResponse, ...]
    matched_event_count: int = Field(ge=0)
    analyzed_event_count: int = Field(ge=0)
    truncated: bool
    analysis_warning: str | None


class NumericReferenceProfileResponse(BaseModel):
    """Reference numeric statistics and persisted fixed-bin counts."""

    model_config = ConfigDict(frozen=True)

    summary: NumericSummaryResponse
    bin_edges: tuple[float, ...]
    bin_counts: tuple[int, ...]


class FeatureReferenceProfileResponse(BaseModel):
    """One stable feature-index reference distribution."""

    model_config = ConfigDict(frozen=True)

    feature_index: int = Field(ge=0)
    profile: NumericReferenceProfileResponse


class RegressionPredictionReferenceResponse(BaseModel):
    """Regression prediction reference distribution."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["regression"] = "regression"
    profile: NumericReferenceProfileResponse


class ClassificationPredictionReferenceResponse(BaseModel):
    """Classification predicted-label reference frequencies."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["classification"] = "classification"
    profile: ClassificationPredictionProfileResponse


PredictionReferenceResponse = Annotated[
    RegressionPredictionReferenceResponse | ClassificationPredictionReferenceResponse,
    Field(discriminator="kind"),
]


class ModelReferenceProfileResponse(BaseModel):
    """Immutable profile owned by an exact registered model version."""

    model_config = ConfigDict(frozen=True)

    profile_id: UUID
    registered_model_name: str = Field(
        examples=["ai_core_random_forest_regression"],
    )
    model_version: str = Field(examples=["7"])
    trainer_key: TrainerKeyResponse
    source: ReferenceProfileSource
    feature_count: int = Field(gt=0)
    features: tuple[FeatureReferenceProfileResponse, ...]
    prediction: PredictionReferenceResponse
    sample_count: int = Field(gt=0)
    training_job_id: UUID
    created_at: datetime


class DriftThresholdsResponse(BaseModel):
    """Operational thresholds applied to this report."""

    model_config = ConfigDict(frozen=True)

    warning: float = Field(ge=0)
    critical: float = Field(gt=0)
    missing_rate_warning: float = Field(ge=0, le=1)
    out_of_range_warning: float = Field(ge=0, le=1)
    epsilon: float = Field(gt=0)


class FeatureDriftResponse(BaseModel):
    """Feature PSI and quality-rate shift."""

    model_config = ConfigDict(frozen=True)

    feature_index: int = Field(ge=0)
    psi: float | None = Field(default=None, ge=0)
    reference_sample_count: int = Field(ge=0)
    current_sample_count: int = Field(ge=0)
    missing_rate_difference: float | None
    out_of_reference_range_proportion: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    severity: DriftSeverity


class RegressionPredictionDriftResponse(BaseModel):
    """Regression prediction histogram and moment drift."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["regression"] = "regression"
    psi: float | None = Field(default=None, ge=0)
    mean_shift: float | None
    standard_deviation_ratio: float | None = Field(default=None, ge=0)
    reference_sample_count: int = Field(ge=0)
    current_sample_count: int = Field(ge=0)
    severity: DriftSeverity


class ClassificationPredictionDriftResponse(BaseModel):
    """Predicted-label total-variation drift, not probability drift."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["classification"] = "classification"
    total_variation_distance: float | None = Field(default=None, ge=0, le=1)
    reference_sample_count: int = Field(ge=0)
    current_sample_count: int = Field(ge=0)
    severity: DriftSeverity


PredictionDriftResponse = Annotated[
    RegressionPredictionDriftResponse | ClassificationPredictionDriftResponse,
    Field(discriminator="kind"),
]


class ModelDriftResponse(BaseModel):
    """Exact-version drift with explicit newest-event analysis coverage."""

    model_config = ConfigDict(frozen=True)

    registered_model_name: str = Field(
        examples=["ai_core_random_forest_regression"],
    )
    model_version: str = Field(examples=["7"])
    trainer_key: TrainerKeyResponse
    reference_profile_source: ReferenceProfileSource
    reference_sample_count: int = Field(gt=0)
    current_sample_count: int = Field(ge=0)
    start_at: datetime
    end_at: datetime
    feature_results: tuple[FeatureDriftResponse, ...]
    prediction_result: PredictionDriftResponse
    aggregate_status: DriftSeverity
    thresholds: DriftThresholdsResponse
    generated_at: datetime
    matched_event_count: int = Field(ge=0)
    analyzed_event_count: int = Field(ge=0)
    truncated: bool
    analysis_warning: str | None

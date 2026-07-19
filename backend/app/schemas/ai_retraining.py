"""Validated API transport for controlled model retraining."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring import DriftSeverity
from app.ml.retraining import (
    ComparisonStatus,
    RetrainingDecisionStatus,
    RetrainingEvaluationMode,
    RetrainingRequestStatus,
    RetrainingTriggerType,
)

ModelName = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9_]{2,127}$"),
]
MinimumDriftStatus = Literal[DriftSeverity.WARNING, DriftSeverity.CRITICAL]


class RetrainingPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allowed_trigger_types: frozenset[RetrainingTriggerType] = frozenset(
        {
            RetrainingTriggerType.FEATURE_DRIFT,
            RetrainingTriggerType.PREDICTION_DRIFT,
            RetrainingTriggerType.DATA_QUALITY,
            RetrainingTriggerType.MANUAL,
        }
    )
    minimum_drift_status: MinimumDriftStatus | None = None
    minimum_current_sample_count: int = Field(default=20, ge=1, le=100_000)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    maximum_requests_per_day: int | None = Field(default=None, ge=1, le=100)
    maximum_requests_per_week: int | None = Field(default=None, ge=1, le=500)
    maximum_active_requests: int | None = Field(default=None, ge=1, le=20)
    require_champion_source: bool = True
    allow_truncated_drift: bool | None = None


class RetrainingPolicyResponse(BaseModel):
    id: UUID
    registered_model_name: str
    enabled: bool
    allowed_trigger_types: frozenset[RetrainingTriggerType]
    minimum_drift_status: DriftSeverity
    minimum_current_sample_count: int
    cooldown_seconds: int
    maximum_requests_per_day: int
    maximum_requests_per_week: int
    maximum_active_requests: int
    require_champion_source: bool
    allow_truncated_drift: bool
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class RetrainingEvaluationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_type: RetrainingTriggerType = RetrainingTriggerType.FEATURE_DRIFT
    start_at: datetime | None = None
    end_at: datetime | None = None
    minimum_sample_count: int | None = Field(default=None, ge=1, le=100_000)
    submit_if_eligible: bool = True


class ManualRetrainingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)
    override_cooldown: bool = False


class CooldownResponse(BaseModel):
    active: bool
    started_at: datetime | None
    expires_at: datetime | None
    remaining_seconds: int


class QuotaResponse(BaseModel):
    requests_today: int
    requests_this_week: int
    active_requests: int
    maximum_per_day: int
    maximum_per_week: int
    maximum_active: int


class RetrainingDecisionResponse(BaseModel):
    registered_model_name: str
    source_model_version: str | None
    requested_alias: str | None
    trigger_type: RetrainingTriggerType
    trigger_reference: str
    aggregate_status: DriftSeverity | None
    matched_event_count: int
    analyzed_event_count: int
    current_sample_count: int
    truncated: bool
    analysis_warning: str | None
    thresholds: dict[str, float]
    decision_status: RetrainingDecisionStatus
    reasons: tuple[str, ...]
    evaluated_at: datetime
    cooldown: CooldownResponse
    quota: QuotaResponse
    existing_request_id: UUID | None


class MetricComparisonResponse(BaseModel):
    metric: str
    source_value: float
    candidate_value: float
    higher_is_better: bool
    outcome: ComparisonStatus


class CandidateComparisonResponse(BaseModel):
    status: ComparisonStatus
    metrics: tuple[MetricComparisonResponse, ...]
    source_model_version: str
    candidate_model_version: str
    compared_at: datetime


class RetrainingRequestResponse(BaseModel):
    id: UUID
    registered_model_name: str
    source_model_version: str
    source_training_job_id: UUID
    algorithm: AlgorithmType
    task_type: TaskType
    trigger_type: RetrainingTriggerType
    trigger_reference: str
    policy_id: UUID
    decision_status: RetrainingDecisionStatus
    request_status: RetrainingRequestStatus
    evaluation_mode: RetrainingEvaluationMode
    training_job_id: UUID | None
    monitoring_evaluation_id: UUID | None
    resulting_model_version: str | None
    requested_by_user_id: UUID
    reason: str | None
    override_used: bool
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    safe_failure_code: str | None
    safe_failure_message: str | None
    comparison: CandidateComparisonResponse | None
    created_at: datetime
    updated_at: datetime


class RetrainingEvaluationResponse(BaseModel):
    decision: RetrainingDecisionResponse
    request: RetrainingRequestResponse | None


class RetrainingRequestPageResponse(BaseModel):
    items: tuple[RetrainingRequestResponse, ...]
    total: int
    limit: int
    offset: int


class RetrainingStatusResponse(BaseModel):
    total_requests: int
    active_requests: int
    completed_requests: int
    failed_requests: int


class RetrainingAuditResponse(BaseModel):
    id: UUID
    policy_id: UUID
    decision: RetrainingDecisionResponse
    evaluated_by_user_id: UUID
    evaluation_mode: RetrainingEvaluationMode
    override_used: bool
    override_reason: str | None
    created_request_id: UUID | None
    monitoring_evaluation_id: UUID | None


class RetrainingAuditPageResponse(BaseModel):
    items: tuple[RetrainingAuditResponse, ...]
    total: int
    limit: int
    offset: int

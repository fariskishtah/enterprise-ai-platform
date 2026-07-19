"""Transport schemas for background jobs and controlled promotion."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from app.ml.jobs import TrainingJobStatus
from app.ml.promotion import (
    ModelAlias,
    PromotionAction,
    PromotionDecision,
    PromotionOperationOutcome,
)
from app.schemas.ai import TrainerKeyResponse

PromotionReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=2000),
]


class TrainingJobSubmissionResponse(BaseModel):
    """Accepted background-job identifier and polling location."""

    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: TrainingJobStatus
    submitted_at: datetime
    status_url: str


class TrainingJobResponse(BaseModel):
    """Safe status snapshot for one authorized training job."""

    model_config = ConfigDict(frozen=True)

    job_id: UUID
    requested_by_user_id: UUID
    trainer_key: TrainerKeyResponse
    status: TrainingJobStatus
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancelled_at: datetime | None
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(gt=0)
    metrics: dict[str, float] | None
    local_execution_run_id: UUID | None
    mlflow_experiment_id: str | None
    mlflow_run_id: str | None
    registered_model_name: str
    registered_model_version: str | None
    error_code: str | None
    safe_error_message: str | None


class TrainingJobPageResponse(BaseModel):
    """Paginated background-job snapshots."""

    model_config = ConfigDict(frozen=True)

    items: list[TrainingJobResponse]
    total: int = Field(ge=0)
    limit: int = Field(gt=0)
    offset: int = Field(ge=0)


class ModelPromotionBody(BaseModel):
    """Optional explicit override controls for a promotion attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    force: StrictBool = False
    reason: PromotionReason | None = None


class PromotionEvaluationResponse(BaseModel):
    """Policy recommendation returned with a completed promotion."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    reason: str
    primary_metric: str
    candidate_value: float | None
    incumbent_value: float | None
    improvement: float | None
    safeguards: dict[str, bool]


class ModelPromotionResponse(BaseModel):
    """Safe result of a verified alias assignment."""

    model_config = ConfigDict(frozen=True)

    audit_id: UUID
    registered_model_name: str
    selected_version: str
    target_alias: ModelAlias
    previous_version: str | None
    policy_evaluation: PromotionEvaluationResponse
    overridden: bool
    completed_at: datetime


class ModelAliasResponse(BaseModel):
    """One governed alias and its exact current holder."""

    model_config = ConfigDict(frozen=True)

    alias: str
    version: str


class ModelAliasesResponse(BaseModel):
    """Bounded alias state for one registered model."""

    model_config = ConfigDict(frozen=True)

    registered_model_name: str
    aliases: list[ModelAliasResponse]


class PromotionAuditResponse(BaseModel):
    """Safe immutable history for one promotion attempt."""

    model_config = ConfigDict(frozen=True)

    audit_id: UUID
    registered_model_name: str
    model_version: str
    trainer_key: TrainerKeyResponse
    target_alias: ModelAlias
    previous_version: str | None
    requested_by_user_id: UUID
    action: PromotionAction
    decision: PromotionDecision
    policy_result: dict[str, object]
    force: bool
    reason: str | None
    operation_outcome: PromotionOperationOutcome
    created_at: datetime
    completed_at: datetime | None
    error_code: str | None
    safe_error_message: str | None


class PromotionAuditPageResponse(BaseModel):
    """Paginated promotion history for a registered model."""

    model_config = ConfigDict(frozen=True)

    items: list[PromotionAuditResponse]
    total: int = Field(ge=0)
    limit: int = Field(gt=0)
    offset: int = Field(ge=0)

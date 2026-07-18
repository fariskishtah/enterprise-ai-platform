"""Transport schemas for persistent background training jobs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ml.jobs import TrainingJobStatus
from app.schemas.ai import TrainerKeyResponse


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

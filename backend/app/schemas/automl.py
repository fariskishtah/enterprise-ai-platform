"""Strict, API-safe AutoML management transport schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.automl.metrics import MetricDirection
from app.ml.automl.models import (
    AutoMLBudgetSpecification,
    AutoMLDataSpecificationReference,
    AutoMLStudySpecification,
    AutoMLStudyStatus,
    AutoMLTrialStatus,
    SamplerType,
)
from app.ml.automl.search_space import PluginAutoMLSearchSpace, SearchParameterKind
from app.ml.domain import TaskType
from app.ml.jobs.models import PreprocessingJobConfig


class AutoMLSearchParameterResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    kind: SearchParameterKind
    default: bool | int | float | str
    low: int | float | None = None
    high: int | float | None = None
    step: int | float | None = None
    choices: list[bool | int | float | str] = Field(default_factory=list)
    log_scale: bool = False


class AutoMLAlgorithmMetadataResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    task_type: TaskType
    probability_support: bool
    parameters: list[AutoMLSearchParameterResponse]


class AutoMLStudyCreateRequest(BaseModel):
    """Validated study intent without raw matrices or arbitrary plugin metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: TaskType
    primary_metric: str = Field(min_length=1, max_length=64)
    metric_direction: MetricDirection
    sampler_type: SamplerType = SamplerType.RANDOM
    random_seed: int = 17
    plugin_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    plugin_search_spaces: tuple[PluginAutoMLSearchSpace, ...] = Field(
        min_length=1, max_length=32
    )
    preprocessing: PreprocessingJobConfig = Field(
        default_factory=PreprocessingJobConfig
    )
    data: AutoMLDataSpecificationReference
    budget: AutoMLBudgetSpecification
    register_champion: bool = False
    registered_model_name: str | None = None

    @model_validator(mode="after")
    def validate_domain_contract(self) -> AutoMLStudyCreateRequest:
        if self.data.dataset_version_id is not None and any(
            value is not None
            for value in (
                self.data.dataset_schema_snapshot,
                self.data.training_data_fingerprint,
                self.data.evaluation_data_fingerprint,
                self.data.training_row_count,
                self.data.evaluation_row_count,
                self.data.feature_count,
                self.data.training_features,
                self.data.training_targets,
                self.data.evaluation_features,
                self.data.evaluation_targets,
            )
        ):
            raise ValueError(
                "Select exactly one AutoML data source: inline data or "
                "dataset_version_id."
            )
        self.to_specification()
        return self

    def to_specification(self) -> AutoMLStudySpecification:
        return AutoMLStudySpecification(**self.model_dump())


class AutoMLStudySummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    study_id: UUID
    requested_by_user_id: UUID
    task_type: TaskType
    status: AutoMLStudyStatus
    primary_metric: str
    metric_direction: MetricDirection
    plugin_ids: list[str]
    trial_budget: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None


class AutoMLStudyDetailResponse(AutoMLStudySummaryResponse):
    random_seed: int
    sampler_type: SamplerType
    search_spaces: list[dict[str, object]]
    preprocessing: dict[str, object]
    data_specification: dict[str, object]
    cross_validation_folds: int
    time_budget_seconds: int
    per_trial_timeout_seconds: int
    max_concurrent_trials: int
    register_champion: bool
    registered_model_name: str | None
    best_trial_id: UUID | None
    champion_training_job_id: UUID | None
    error_code: str | None
    safe_error_message: str | None


class AutoMLTrialSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: UUID
    study_id: UUID
    trial_number: int
    plugin_id: str
    status: AutoMLTrialStatus
    primary_metric_value: float | None
    duration_seconds: float | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AutoMLTrialDetailResponse(AutoMLTrialSummaryResponse):
    parameters: dict[str, object]
    attempt_count: int
    max_attempts: int
    fold_metrics: list[dict[str, float]] | None
    aggregate_metrics: dict[str, float] | None
    error_code: str | None
    safe_error_message: str | None


class AutoMLStudyListResponse(BaseModel):
    items: list[AutoMLStudySummaryResponse]
    total: int
    limit: int
    offset: int


class AutoMLTrialListResponse(BaseModel):
    items: list[AutoMLTrialSummaryResponse]
    total: int
    limit: int
    offset: int


class AutoMLLeaderboardEntryResponse(BaseModel):
    rank: int = Field(ge=1)
    trial_id: UUID
    trial_number: int
    plugin_id: str
    status: AutoMLTrialStatus
    primary_metric_value: float | None
    metric_standard_deviation: float | None
    duration_seconds: float | None
    parameters: dict[str, object]


class AutoMLStudySubmissionResponse(BaseModel):
    study_id: UUID
    status: AutoMLStudyStatus
    submitted_at: datetime
    status_url: str
    created: bool


class AutoMLCancelResponse(BaseModel):
    study_id: UUID
    status: AutoMLStudyStatus
    cancellation: Literal["cancelled", "requested", "unchanged"]
    cancel_requested_at: datetime | None
    cancelled_at: datetime | None


IdempotencyKey = Annotated[str, Field(min_length=1, max_length=128)]

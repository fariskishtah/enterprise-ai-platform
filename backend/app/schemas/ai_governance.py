"""Transport schemas for background jobs and controlled promotion."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.ml.domain import TaskType
from app.ml.jobs import TrainingJobStatus
from app.ml.promotion import (
    ModelAlias,
    PromotionAction,
    PromotionDecision,
    PromotionOperationOutcome,
)
from app.ml.training_limits import MAX_EVALUATION_ROWS, MAX_TRAINING_ROWS
from app.schemas.ai import TrainerKeyResponse

PromotionReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=2000),
]


class AlgorithmParameterResponse(BaseModel):
    """Stable public description of one allowlisted hyperparameter."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    default: int | float | bool | str
    minimum: float | None
    maximum: float | None
    choices: list[str]
    description: str


class AlgorithmResponse(BaseModel):
    """Safe public model-plugin metadata used by dynamic clients."""

    model_config = ConfigDict(frozen=True)

    id: str
    algorithm_family: str
    display_name: str
    description: str
    supported_tasks: list[TaskType]
    parameters: list[AlgorithmParameterResponse]
    default_parameters: dict[str, int | float | bool | str]
    scaling_behavior: str
    probability_support: bool
    decision_function_support: bool
    feature_importance_support: bool
    coefficient_support: bool
    permutation_importance_support: bool
    global_explainability: bool
    local_explainability: bool
    dependency_available: bool


class GenericPreprocessingRequest(BaseModel):
    """Allowlisted numeric preprocessing for a generic training job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scaler: str = Field(default="auto", pattern="^(auto|none|standard|minmax|robust)$")
    imputer: str = Field(default="none", pattern="^(none|mean|median|most_frequent)$")


class GenericTrainingJobRequest(BaseModel):
    """Generic, allowlisted background training request for numeric matrices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: TaskType
    algorithm: str = Field(min_length=3, max_length=64)
    dataset_version_id: UUID | None = None
    training_features: list[list[FiniteFloat]] | None = Field(
        default=None, min_length=2, max_length=MAX_TRAINING_ROWS
    )
    training_targets: list[StrictInt | FiniteFloat] | None = Field(
        default=None, min_length=2, max_length=MAX_TRAINING_ROWS
    )
    evaluation_features: list[list[FiniteFloat]] | None = Field(
        default=None, min_length=2, max_length=MAX_EVALUATION_ROWS
    )
    evaluation_targets: list[StrictInt | FiniteFloat] | None = Field(
        default=None, min_length=2, max_length=MAX_EVALUATION_ROWS
    )
    hyperparameters: dict[str, object] = Field(default_factory=dict, max_length=32)
    preprocessing: GenericPreprocessingRequest = Field(
        default_factory=GenericPreprocessingRequest
    )
    random_seed: StrictInt | None = 17
    experiment_name: str = Field(min_length=1, max_length=255)
    run_name: str | None = Field(default=None, min_length=1, max_length=255)
    registered_model_name: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{2,127}$"
    )
    tags: dict[str, str] = Field(default_factory=dict, max_length=20)
    model_description: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("training_features", "evaluation_features", mode="before")
    @classmethod
    def reject_boolean_features(cls, value: object) -> object:
        if isinstance(value, list) and any(
            isinstance(item, bool)
            for row in value
            if isinstance(row, list)
            for item in row
        ):
            raise ValueError("Feature matrices cannot contain boolean values.")
        return value

    @model_validator(mode="after")
    def validate_matrix_and_target_shapes(self) -> "GenericTrainingJobRequest":
        values = (
            self.training_features,
            self.training_targets,
            self.evaluation_features,
            self.evaluation_targets,
        )
        if self.dataset_version_id is not None:
            if any(value is not None for value in values):
                raise ValueError(
                    "Select exactly one training data source: inline matrices or "
                    "dataset_version_id."
                )
            return self
        if any(value is None for value in values):
            raise ValueError(
                "Inline training requires all feature and target matrices."
            )
        assert self.training_features is not None
        assert self.training_targets is not None
        assert self.evaluation_features is not None
        assert self.evaluation_targets is not None
        matrices = (self.training_features, self.evaluation_features)
        widths = []
        for matrix in matrices:
            if not matrix or not matrix[0]:
                raise ValueError("Feature matrices must contain feature columns.")
            width = len(matrix[0])
            if any(len(row) != width for row in matrix):
                raise ValueError("Feature matrices must be rectangular.")
            widths.append(width)
        if widths[0] != widths[1]:
            raise ValueError("Training and evaluation feature widths must match.")
        if len(self.training_features) != len(self.training_targets):
            raise ValueError("Training feature and target row counts must match.")
        if len(self.evaluation_features) != len(self.evaluation_targets):
            raise ValueError("Evaluation feature and target row counts must match.")
        if self.task_type is TaskType.CLASSIFICATION:
            if any(type(value) is not int for value in self.training_targets):
                raise ValueError("Classification targets must be integer labels.")
            if any(type(value) is not int for value in self.evaluation_targets):
                raise ValueError("Classification targets must be integer labels.")
            if len(set(self.training_targets)) < 2:
                raise ValueError(
                    "Classification training requires at least two classes."
                )
        return self


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
    dataset_version_id: UUID | None
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

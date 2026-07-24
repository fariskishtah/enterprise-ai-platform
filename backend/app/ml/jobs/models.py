"""Immutable contracts for persistent background training jobs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_serializer,
    model_validator,
)

from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.plugins import create_default_plugin_registry
from app.ml.registry.naming import validate_registered_model_name
from app.ml.trainers.random_forest import (
    RandomForestClassificationParameters,
    RandomForestRegressionParameters,
)
from app.ml.training_limits import (
    MAX_EVALUATION_ROWS,
    MAX_MODEL_DESCRIPTION_LENGTH,
    MAX_TRAINING_ROWS,
    MAX_TRAINING_RUN_NAME_LENGTH,
    MAX_TRAINING_TAG_KEY_LENGTH,
    MAX_TRAINING_TAG_VALUE_LENGTH,
    MAX_TRAINING_TAGS,
    validate_training_matrix_limits,
)

StrictFiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
PLUGIN_REGISTRY = create_default_plugin_registry()


class TrainingJobStatus(StrEnum):
    """Persisted states for one background training execution."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class _BaseRandomForestJobSpec(BaseModel):
    """JSON-compatible values shared by the supported background tasks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    training_features: tuple[tuple[StrictFiniteFloat, ...], ...] = Field(
        min_length=1,
        max_length=MAX_TRAINING_ROWS,
    )
    evaluation_features: tuple[tuple[StrictFiniteFloat, ...], ...] = Field(
        min_length=1,
        max_length=MAX_EVALUATION_ROWS,
    )
    dataset_version_id: UUID | None = None
    dataset_schema_snapshot: dict[str, object] | None = None
    random_seed: StrictInt | None = None
    experiment_name: str
    run_name: str | None = None
    registered_model_name: str
    tags: Mapping[str, str] = Field(max_length=MAX_TRAINING_TAGS)
    model_description: str | None = None

    @model_validator(mode="after")
    def validate_common_values(self) -> _BaseRandomForestJobSpec:
        """Validate matrices and bounded integration metadata."""
        training_width = _matrix_width(
            self.training_features,
            name="training_features",
        )
        evaluation_width = _matrix_width(
            self.evaluation_features,
            name="evaluation_features",
        )
        if training_width != evaluation_width:
            raise ValueError(
                "training and evaluation features must have equal column counts.",
            )
        validate_training_matrix_limits(
            training_rows=len(self.training_features),
            evaluation_rows=len(self.evaluation_features),
            feature_columns=training_width,
        )
        _bounded_text(self.experiment_name, name="experiment_name", maximum=255)
        if self.run_name is not None:
            _bounded_text(
                self.run_name,
                name="run_name",
                maximum=MAX_TRAINING_RUN_NAME_LENGTH,
            )
        if self.model_description is not None:
            _bounded_text(
                self.model_description,
                name="model_description",
                maximum=MAX_MODEL_DESCRIPTION_LENGTH,
            )
        validate_registered_model_name(self.registered_model_name)
        for key, value in self.tags.items():
            _bounded_text(
                key,
                name="tag key",
                maximum=MAX_TRAINING_TAG_KEY_LENGTH,
            )
            _bounded_text(
                value,
                name="tag value",
                maximum=MAX_TRAINING_TAG_VALUE_LENGTH,
            )
        object.__setattr__(self, "tags", MappingProxyType(dict(self.tags)))
        return self

    def payload(self) -> dict[str, object]:
        """Return a detached JSON representation suitable for persistence."""
        return self.model_dump(mode="json")

    @field_serializer("tags")
    def serialize_tags(self, tags: Mapping[str, str]) -> dict[str, str]:
        """Serialize the detached read-only mapping as ordinary JSON data."""
        return dict(tags)

    def fingerprint(self) -> str:
        """Return the SHA-256 digest of canonical JSON request data."""
        canonical = json.dumps(
            self.payload(),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()


class RandomForestRegressionJobSpec(_BaseRandomForestJobSpec):
    """Validated persisted specification for regression training."""

    training_targets: tuple[StrictFiniteFloat, ...] = Field(
        min_length=1,
        max_length=MAX_TRAINING_ROWS,
    )
    evaluation_targets: tuple[StrictFiniteFloat, ...] = Field(
        min_length=1,
        max_length=MAX_EVALUATION_ROWS,
    )
    hyperparameters: RandomForestRegressionParameters

    @model_validator(mode="after")
    def validate_target_lengths(self) -> RandomForestRegressionJobSpec:
        """Require one regression target per feature row."""
        if len(self.training_features) != len(self.training_targets):
            raise ValueError("training feature and target row counts must match.")
        if len(self.evaluation_features) != len(self.evaluation_targets):
            raise ValueError("evaluation feature and target row counts must match.")
        return self


class RandomForestClassificationJobSpec(_BaseRandomForestJobSpec):
    """Validated persisted specification for integer-label classification."""

    training_targets: tuple[StrictInt, ...] = Field(
        min_length=1,
        max_length=MAX_TRAINING_ROWS,
    )
    evaluation_targets: tuple[StrictInt, ...] = Field(
        min_length=1,
        max_length=MAX_EVALUATION_ROWS,
    )
    hyperparameters: RandomForestClassificationParameters

    @model_validator(mode="after")
    def validate_target_lengths(self) -> RandomForestClassificationJobSpec:
        """Require one label per row and at least two training classes."""
        if len(self.training_features) != len(self.training_targets):
            raise ValueError("training feature and target row counts must match.")
        if len(self.evaluation_features) != len(self.evaluation_targets):
            raise ValueError("evaluation feature and target row counts must match.")
        if len(set(self.training_targets)) < 2:
            raise ValueError("classification training requires at least two classes.")
        return self


class PreprocessingJobConfig(BaseModel):
    """Allowlisted preprocessing persisted with a generic model job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scaler: str = Field(default="auto", pattern="^(auto|none|standard|minmax|robust)$")
    imputer: str = Field(
        default="none",
        pattern="^(none|mean|median|most_frequent)$",
    )


class _BasePluginJobSpec(_BaseRandomForestJobSpec):
    """Shared persisted fields for a non-Random-Forest plugin job."""

    plugin_id: str = Field(min_length=3, max_length=64)
    hyperparameters: dict[str, object] = Field(default_factory=dict, max_length=32)
    preprocessing: PreprocessingJobConfig = Field(
        default_factory=PreprocessingJobConfig
    )

    def plugin_key(self) -> TrainerKey:
        return PLUGIN_REGISTRY.get(self.plugin_id).key


class PluginRegressionJobSpec(_BasePluginJobSpec):
    """Validated generic regression training specification."""

    training_targets: tuple[StrictFiniteFloat, ...] = Field(
        min_length=2,
        max_length=MAX_TRAINING_ROWS,
    )
    evaluation_targets: tuple[StrictFiniteFloat, ...] = Field(
        min_length=2,
        max_length=MAX_EVALUATION_ROWS,
    )

    @model_validator(mode="after")
    def validate_plugin_regression(self) -> PluginRegressionJobSpec:
        plugin = PLUGIN_REGISTRY.get(self.plugin_id, TaskType.REGRESSION)
        plugin.validate_parameters(self.hyperparameters)
        if len(self.training_features) != len(self.training_targets):
            raise ValueError("training feature and target row counts must match.")
        if len(self.evaluation_features) != len(self.evaluation_targets):
            raise ValueError("evaluation feature and target row counts must match.")
        return self


class PluginClassificationJobSpec(_BasePluginJobSpec):
    """Validated generic integer-label classification specification."""

    training_targets: tuple[StrictInt, ...] = Field(
        min_length=2,
        max_length=MAX_TRAINING_ROWS,
    )
    evaluation_targets: tuple[StrictInt, ...] = Field(
        min_length=2,
        max_length=MAX_EVALUATION_ROWS,
    )

    @model_validator(mode="after")
    def validate_plugin_classification(self) -> PluginClassificationJobSpec:
        plugin = PLUGIN_REGISTRY.get(self.plugin_id, TaskType.CLASSIFICATION)
        plugin.validate_parameters(self.hyperparameters)
        if len(self.training_features) != len(self.training_targets):
            raise ValueError("training feature and target row counts must match.")
        if len(self.evaluation_features) != len(self.evaluation_targets):
            raise ValueError("evaluation feature and target row counts must match.")
        if len(set(self.training_targets)) < 2:
            raise ValueError("classification training requires at least two classes.")
        return self


type TrainingJobSpec = (
    RandomForestRegressionJobSpec
    | RandomForestClassificationJobSpec
    | PluginRegressionJobSpec
    | PluginClassificationJobSpec
)


@dataclass(frozen=True, slots=True)
class TrainingJobRecord:
    """Repository-owned snapshot of a persistent training job."""

    id: UUID
    company_id: UUID
    requested_by_user_id: UUID
    dataset_version_id: UUID | None
    key: TrainerKey
    status: TrainingJobStatus
    specification: TrainingJobSpec
    queue_message_id: str | None
    attempt_count: int
    max_attempts: int
    state_version: int
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancelled_at: datetime | None
    error_code: str | None
    safe_error_message: str | None
    local_execution_run_id: UUID | None
    mlflow_experiment_id: str | None
    mlflow_run_id: str | None
    registered_model_version: str | None
    metrics: Mapping[str, float] | None

    def __post_init__(self) -> None:
        """Detach the optional mutable metrics snapshot."""
        if self.metrics is not None:
            object.__setattr__(
                self,
                "metrics",
                MappingProxyType(dict(self.metrics)),
            )

    @property
    def registered_model_name(self) -> str:
        """Return the validated model name from the persisted specification."""
        return self.specification.registered_model_name


@dataclass(frozen=True, slots=True)
class TrainingJobSubmission:
    """Submission result including whether a new job was enqueued."""

    job: TrainingJobRecord
    created: bool


def parse_training_job_spec(
    task_type: TaskType,
    algorithm: AlgorithmType,
    payload: Mapping[str, object],
) -> TrainingJobSpec:
    """Revalidate a persisted JSON specification for its explicit task."""
    if algorithm is not AlgorithmType.RANDOM_FOREST or "plugin_id" in payload:
        specification: TrainingJobSpec
        if task_type is TaskType.REGRESSION:
            specification = PluginRegressionJobSpec.model_validate(payload)
        elif task_type is TaskType.CLASSIFICATION:
            specification = PluginClassificationJobSpec.model_validate(payload)
        else:
            raise ValueError(
                f"Unsupported background training task: {task_type.value}."
            )
        if specification.plugin_key().algorithm is not algorithm:
            raise ValueError(
                "Persisted algorithm does not match its plugin specification."
            )
        return specification
    if task_type is TaskType.REGRESSION:
        return RandomForestRegressionJobSpec.model_validate(payload)
    if task_type is TaskType.CLASSIFICATION:
        return RandomForestClassificationJobSpec.model_validate(payload)
    raise ValueError(f"Unsupported background training task: {task_type.value}.")


def random_forest_key(task_type: TaskType) -> TrainerKey:
    """Return the only algorithm family accepted by this milestone."""
    return TrainerKey(AlgorithmType.RANDOM_FOREST, task_type)


def _matrix_width(
    matrix: tuple[tuple[float, ...], ...],
    *,
    name: str,
) -> int:
    if not matrix or not matrix[0]:
        raise ValueError(f"{name} must be non-empty and contain feature columns.")
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ValueError(f"{name} must be rectangular.")
    return width


def _bounded_text(value: str, *, name: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty and at most {maximum} characters.")

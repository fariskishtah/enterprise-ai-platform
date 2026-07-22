"""Immutable pure-domain contracts for future AutoML orchestration."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    model_validator,
)

from app.ml.automl.metrics import MetricDirection, require_automl_metric
from app.ml.automl.search_space import PluginAutoMLSearchSpace, SafeName
from app.ml.domain import TaskType
from app.ml.jobs.models import PreprocessingJobConfig
from app.ml.registry.naming import validate_registered_model_name
from app.ml.training_limits import MAX_EVALUATION_ROWS, MAX_TRAINING_ROWS

Sha256Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
StrictFiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class AutoMLStudyStatus(StrEnum):
    """Future persisted study lifecycle values."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AutoMLTrialStatus(StrEnum):
    """Future persisted trial lifecycle values."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PRUNED = "pruned"
    CANCELLED = "cancelled"


class SamplerType(StrEnum):
    """Allowlisted study samplers in the initial milestone."""

    RANDOM = "random"


class AutoMLBudgetSpecification(BaseModel):
    """Conservative immutable limits for a future study."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trial_budget: int = Field(ge=1, le=100)
    time_budget_seconds: int = Field(ge=60, le=86_400)
    per_trial_timeout_seconds: int = Field(ge=10, le=21_600)
    max_concurrent_trials: int = Field(ge=1, le=4)
    cross_validation_folds: int = Field(ge=2, le=10)

    @model_validator(mode="after")
    def validate_related_limits(self) -> AutoMLBudgetSpecification:
        if self.per_trial_timeout_seconds > self.time_budget_seconds:
            raise ValueError("Per-trial timeout cannot exceed the study time budget.")
        if self.max_concurrent_trials > self.trial_budget:
            raise ValueError("Concurrent trials cannot exceed the trial budget.")
        return self


class AutoMLDataSpecificationReference(BaseModel):
    """Bounded non-secret metadata identifying validated matrix inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version_id: UUID | None = None
    dataset_schema_snapshot: dict[str, object] | None = None
    training_data_fingerprint: Sha256Digest | None = None
    evaluation_data_fingerprint: Sha256Digest | None = None
    training_row_count: int | None = Field(default=None, ge=2, le=MAX_TRAINING_ROWS)
    evaluation_row_count: int | None = Field(default=None, ge=2, le=MAX_EVALUATION_ROWS)
    feature_count: int | None = Field(default=None, ge=1, le=10_000)
    training_features: tuple[tuple[StrictFiniteFloat, ...], ...] | None = Field(
        default=None, min_length=2, max_length=MAX_TRAINING_ROWS
    )
    training_targets: tuple[StrictInt | StrictFiniteFloat, ...] | None = Field(
        default=None, min_length=2, max_length=MAX_TRAINING_ROWS
    )
    evaluation_features: tuple[tuple[StrictFiniteFloat, ...], ...] | None = Field(
        default=None, min_length=2, max_length=MAX_EVALUATION_ROWS
    )
    evaluation_targets: tuple[StrictInt | StrictFiniteFloat, ...] | None = Field(
        default=None, min_length=2, max_length=MAX_EVALUATION_ROWS
    )

    @model_validator(mode="after")
    def validate_execution_snapshot(self) -> AutoMLDataSpecificationReference:
        metadata = (
            self.training_data_fingerprint,
            self.evaluation_data_fingerprint,
            self.training_row_count,
            self.evaluation_row_count,
            self.feature_count,
        )
        values = (
            self.training_features,
            self.training_targets,
            self.evaluation_features,
            self.evaluation_targets,
        )
        if self.dataset_version_id is not None and all(
            value is None for value in (*metadata, *values)
        ):
            return self
        if any(value is None for value in metadata):
            raise ValueError("AutoML data metadata must be supplied as a complete set.")
        if all(value is None for value in values):
            return self
        if any(value is None for value in values):
            raise ValueError(
                "AutoML execution data must be supplied as a complete set."
            )
        assert self.training_features is not None
        assert self.training_targets is not None
        assert self.evaluation_features is not None
        assert self.evaluation_targets is not None
        assert self.training_row_count is not None
        assert self.evaluation_row_count is not None
        assert self.feature_count is not None
        matrices = (self.training_features, self.evaluation_features)
        if any(
            not matrix or any(len(row) != self.feature_count for row in matrix)
            for matrix in matrices
        ):
            raise ValueError("AutoML feature matrices must match feature_count.")
        if len(self.training_features) != len(self.training_targets):
            raise ValueError("AutoML training rows and targets must align.")
        if len(self.evaluation_features) != len(self.evaluation_targets):
            raise ValueError("AutoML evaluation rows and targets must align.")
        if len(self.training_features) != self.training_row_count:
            raise ValueError("AutoML training row metadata must match the snapshot.")
        if len(self.evaluation_features) != self.evaluation_row_count:
            raise ValueError("AutoML evaluation row metadata must match the snapshot.")
        return self

    @property
    def executable(self) -> bool:
        return self.training_features is not None


class AutoMLStudySpecification(BaseModel):
    """Validated study intent without persistence or execution behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: TaskType
    primary_metric: SafeName
    metric_direction: MetricDirection
    sampler_type: SamplerType = SamplerType.RANDOM
    random_seed: StrictInt = 17
    plugin_ids: tuple[SafeName, ...] = Field(min_length=1, max_length=32)
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
    def validate_study(self) -> AutoMLStudySpecification:
        if self.task_type is TaskType.CLASSIFICATION and (
            self.data.training_targets is not None
            and self.data.evaluation_targets is not None
            and any(
                type(value) is not int
                for value in (
                    *self.data.training_targets,
                    *self.data.evaluation_targets,
                )
            )
        ):
            raise ValueError("Classification AutoML targets must be integer labels.")
        if len(set(self.plugin_ids)) != len(self.plugin_ids):
            raise ValueError("AutoML plugin IDs must be unique.")
        spaces = {space.plugin_id: space for space in self.plugin_search_spaces}
        if len(spaces) != len(self.plugin_search_spaces):
            raise ValueError("AutoML plugin search spaces must be unique.")
        if set(spaces) != set(self.plugin_ids):
            raise ValueError("Every AutoML plugin must have exactly one search space.")
        if any(space.task_type is not self.task_type for space in spaces.values()):
            raise ValueError("Every AutoML plugin must match the study task.")
        metric = require_automl_metric(
            self.primary_metric,
            task_type=self.task_type,
            direction=self.metric_direction,
        )
        if metric.requires_probabilities and any(
            not space.probability_support for space in spaces.values()
        ):
            raise ValueError(
                "The primary metric requires probability support from every plugin."
            )
        from app.ml.automl.search_space import validate_narrowed_search_space
        from app.ml.plugins import create_default_plugin_registry

        registry = create_default_plugin_registry()
        for plugin_id, search_space in spaces.items():
            plugin = registry.get(plugin_id, self.task_type)
            if plugin.automl_search_space is None:
                raise ValueError("Every study plugin must explicitly support AutoML.")
            plugin.validate_automl_search_space(search_space)
            validate_narrowed_search_space(plugin.automl_search_space, search_space)
        if self.register_champion:
            if self.registered_model_name is None:
                raise ValueError(
                    "Champion registration requires a registered model name."
                )
            validate_registered_model_name(self.registered_model_name)
        elif self.registered_model_name is not None:
            raise ValueError("A registered model name requires champion registration.")
        return self

    def fingerprint(self) -> str:
        """Return a stable digest of the complete JSON-safe study intent."""
        return _fingerprint(self.model_dump(mode="json"))


class AutoMLTrialSpecification(BaseModel):
    """One deterministic sampled trial specification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_seed: StrictInt
    trial_number: int = Field(ge=0)
    plugin_id: SafeName
    sampled_parameters: dict[str, StrictBool | StrictInt | FiniteFloat | str] = Field(
        max_length=32
    )
    trial_seed: StrictInt
    parameter_fingerprint: Sha256Digest

    @model_validator(mode="after")
    def validate_parameter_fingerprint(self) -> AutoMLTrialSpecification:
        if parameter_fingerprint(self.sampled_parameters) != self.parameter_fingerprint:
            raise ValueError("The parameter fingerprint does not match the sample.")
        return self


def parameter_fingerprint(
    parameters: dict[str, bool | int | float | str],
) -> str:
    """Return a stable digest for a finite JSON-safe parameter mapping."""
    return _fingerprint(parameters)


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()

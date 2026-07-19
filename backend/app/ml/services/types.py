"""Immutable tracked-training and registered-prediction application types."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from app.ml.base import TrainerKey
from app.ml.engine import TrainingExecutionPlan, TrainingExecutionResult
from app.ml.metrics import MetricsReport
from app.ml.registry import (
    RegisteredModelVersion,
    validate_registered_model_name,
    validate_version_or_alias,
)
from app.ml.tracking import (
    ExperimentRunInfo,
    TrackingParameterValue,
    normalize_tracking_parameters,
    normalize_tracking_tags,
)


@dataclass(frozen=True, slots=True)
class TrackedTrainingRequest[
    TrainerT,
    FeaturesT,
    TargetsT,
    ModelT,
    PredictionsT,
    ReportT: MetricsReport,
]:
    """Typed local plan plus metadata required for tracking and registration."""

    plan: TrainingExecutionPlan[
        TrainerT,
        FeaturesT,
        TargetsT,
        ModelT,
        PredictionsT,
        ReportT,
    ]
    experiment_name: str
    run_name: str | None
    registered_model_name: str
    tracking_parameters: Mapping[str, TrackingParameterValue]
    tracking_tags: Mapping[str, str]
    model_description: str | None

    def __post_init__(self) -> None:
        """Validate names and detach supplied mutable mappings."""
        if not self.experiment_name.strip() or len(self.experiment_name) > 255:
            raise ValueError(
                "experiment_name must be a non-empty string of at most 255 characters.",
            )
        if self.run_name is not None and (
            not self.run_name.strip() or len(self.run_name) > 255
        ):
            raise ValueError(
                "run_name must be a non-empty string of at most 255 characters.",
            )
        validate_registered_model_name(self.registered_model_name)
        if self.model_description is not None and (
            not self.model_description.strip() or len(self.model_description) > 5000
        ):
            raise ValueError(
                "model_description must be non-empty and at most 5000 characters.",
            )
        object.__setattr__(
            self,
            "tracking_parameters",
            normalize_tracking_parameters(self.tracking_parameters),
        )
        object.__setattr__(
            self,
            "tracking_tags",
            normalize_tracking_tags(self.tracking_tags),
        )


@dataclass(frozen=True, slots=True)
class TrackedTrainingResult[ModelT, ReportT: MetricsReport]:
    """Combined result after local execution, tracking, and registration."""

    execution: TrainingExecutionResult[ModelT, ReportT]
    tracking: ExperimentRunInfo
    registered_model: RegisteredModelVersion


@dataclass(frozen=True, slots=True)
class RegisteredPredictionRequest[FeaturesT]:
    """Prepared features and one registered model version reference."""

    registered_model_name: str
    version_or_alias: str
    features: FeaturesT

    def __post_init__(self) -> None:
        """Validate the registry reference without modifying features."""
        validate_registered_model_name(self.registered_model_name)
        validate_version_or_alias(self.version_or_alias)


@dataclass(frozen=True, slots=True)
class RegisteredPredictionResult[PredictionsT]:
    """Typed predictions paired with the exact resolved model version."""

    model_version: RegisteredModelVersion
    predictions: PredictionsT


@dataclass(frozen=True, slots=True)
class RegisteredPredictionPlan[ModelT, FeaturesT, PredictionsT]:
    """Bind a model type, trainer key, validation, and raw prediction behavior."""

    key: TrainerKey
    expected_model_type: type[ModelT]
    validate_features: Callable[[object], FeaturesT]
    predict: Callable[[ModelT, FeaturesT], PredictionsT]


class RegisteredPredictionObserver(Protocol):
    """Optional application observer for safe model-resolution metadata."""

    def model_resolved(self, version: RegisteredModelVersion) -> None:
        """Receive the resolved version before loading or prediction."""

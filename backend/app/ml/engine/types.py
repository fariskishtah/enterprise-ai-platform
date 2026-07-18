"""Immutable generic input, plan, and result contracts for local training."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.ml.artifacts import ArtifactInfo
from app.ml.base import BaseTrainer, TrainerInput, TrainerKey
from app.ml.domain import TrainingResult
from app.ml.factory import TrainerRegistration
from app.ml.metrics import BaseMetricsEngine, MetricsReport


@dataclass(frozen=True, slots=True)
class TrainingExecutionInput[TrainerT, FeaturesT, TargetsT]:
    """Prepared training and evaluation data with one typed registration."""

    registration: TrainerRegistration[TrainerT]
    training_input: TrainerInput[FeaturesT, TargetsT]
    evaluation_features: FeaturesT
    evaluation_targets: TargetsT


@dataclass(frozen=True, slots=True)
class TrainingExecutionPlan[
    TrainerT,
    FeaturesT,
    TargetsT,
    ModelT,
    PredictionsT,
    ReportT: MetricsReport,
]:
    """Bind typed execution data, metrics behavior, and expected model type."""

    execution_input: TrainingExecutionInput[
        TrainerT,
        FeaturesT,
        TargetsT,
    ]
    trainer_contract: Callable[
        [TrainerT],
        BaseTrainer[FeaturesT, TargetsT, ModelT, PredictionsT],
    ]
    metrics_engine: BaseMetricsEngine[TargetsT, PredictionsT, ReportT]
    expected_model_type: type[ModelT]


@dataclass(frozen=True, slots=True)
class TrainingExecutionResult[ModelT, ReportT: MetricsReport]:
    """Primary typed result of a successful local training execution."""

    run_id: UUID
    key: TrainerKey
    model: ModelT
    metrics_report: ReportT
    artifact: ArtifactInfo
    training_duration_seconds: float

    def __post_init__(self) -> None:
        """Protect the non-negative training-duration invariant."""
        if self.training_duration_seconds < 0:
            msg = "training_duration_seconds must be greater than or equal to zero."
            raise ValueError(msg)

    def to_training_result(self) -> TrainingResult:
        """Adapt a successful execution to the existing workflow result model."""
        return TrainingResult(
            success=True,
            model_version=str(self.run_id),
            metrics=dict(self.metrics_report.to_mapping()),
            artifact_path=self.artifact.path,
            duration_seconds=self.training_duration_seconds,
            error_message=None,
        )

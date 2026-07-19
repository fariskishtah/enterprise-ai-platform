"""Typed orchestration of fitting, evaluation, and local persistence."""

from collections.abc import Callable
from uuid import UUID, uuid4

from app.ml.artifacts import ArtifactDestination, BaseArtifactManager
from app.ml.engine.exceptions import TrainingModelTypeMismatchError
from app.ml.engine.types import TrainingExecutionPlan, TrainingExecutionResult
from app.ml.factory import TrainerFactory
from app.ml.metrics import MetricsReport

type RunIdFactory = Callable[[], UUID]


class TrainingEngine:
    """Execute one explicit typed plan without selecting concrete components."""

    def __init__(
        self,
        *,
        trainer_factory: TrainerFactory,
        artifact_manager: BaseArtifactManager,
        run_id_factory: RunIdFactory = uuid4,
    ) -> None:
        self._trainer_factory = trainer_factory
        self._artifact_manager = artifact_manager
        self._run_id_factory = run_id_factory

    def execute[
        TrainerT,
        FeaturesT,
        TargetsT,
        ModelT,
        PredictionsT,
        ReportT: MetricsReport,
    ](
        self,
        plan: TrainingExecutionPlan[
            TrainerT,
            FeaturesT,
            TargetsT,
            ModelT,
            PredictionsT,
            ReportT,
        ],
    ) -> TrainingExecutionResult[ModelT, ReportT]:
        """Fit, evaluate, persist, and return one successful execution."""
        run_id = self._run_id_factory()
        execution_input = plan.execution_input
        created_trainer = self._trainer_factory.create(execution_input.registration)
        trainer = plan.trainer_contract(created_trainer)
        trainer_output = trainer.fit(execution_input.training_input)
        if not isinstance(trainer_output.model, plan.expected_model_type):
            msg = (
                f"Trainer for '{trainer.key}' returned "
                f"'{type(trainer_output.model).__name__}', expected "
                f"'{plan.expected_model_type.__name__}'."
            )
            raise TrainingModelTypeMismatchError(msg)

        predictions = trainer.predict(
            trainer_output.model,
            execution_input.evaluation_features,
        )
        metrics_report = plan.metrics_engine.evaluate(
            execution_input.evaluation_targets,
            predictions,
        )
        artifact = self._artifact_manager.save(
            trainer_output.model,
            ArtifactDestination(key=trainer.key, run_id=run_id),
        )
        return TrainingExecutionResult(
            run_id=run_id,
            key=trainer.key,
            model=trainer_output.model,
            metrics_report=metrics_report,
            artifact=artifact,
            training_duration_seconds=trainer_output.training_duration_seconds,
        )

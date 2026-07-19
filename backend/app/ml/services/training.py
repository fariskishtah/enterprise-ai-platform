"""Application orchestration for tracked and registered local training."""

from app.ml.engine import TrainingEngine
from app.ml.metrics import MetricsReport
from app.ml.registry import BaseModelRegistry, ModelRegistrationRequest
from app.ml.services.types import TrackedTrainingRequest, TrackedTrainingResult
from app.ml.tracking import BaseExperimentTracker, ExperimentRunRequest


class TrackedTrainingService:
    """Sequence local execution, successful-run tracking, and registration."""

    def __init__(
        self,
        *,
        training_engine: TrainingEngine,
        experiment_tracker: BaseExperimentTracker,
        model_registry: BaseModelRegistry,
    ) -> None:
        self._training_engine = training_engine
        self._experiment_tracker = experiment_tracker
        self._model_registry = model_registry

    def execute[
        TrainerT,
        FeaturesT,
        TargetsT,
        ModelT,
        PredictionsT,
        ReportT: MetricsReport,
    ](
        self,
        request: TrackedTrainingRequest[
            TrainerT,
            FeaturesT,
            TargetsT,
            ModelT,
            PredictionsT,
            ReportT,
        ],
    ) -> TrackedTrainingResult[ModelT, ReportT]:
        """Return a result only after all three ordered stages succeed.

        Local artifacts remain after tracking failures, and completed MLflow runs
        remain after registry failures. Cross-system rollback is intentionally
        outside this synchronous milestone.
        """
        execution = self._training_engine.execute(request.plan)
        tracking = self._experiment_tracker.log_successful_run(
            ExperimentRunRequest(
                experiment_name=request.experiment_name,
                run_name=request.run_name,
                key=execution.key,
                parameters=request.tracking_parameters,
                metrics=execution.metrics_report.to_mapping(),
                artifact=execution.artifact,
                tags=request.tracking_tags,
            ),
        )
        registered_model = self._model_registry.register(
            ModelRegistrationRequest(
                registered_model_name=request.registered_model_name,
                source_run_id=tracking.run_id,
                artifact_uri=tracking.artifact_uri,
                key=execution.key,
                description=request.model_description,
                tags=request.tracking_tags,
            ),
        )
        return TrackedTrainingResult(
            execution=execution,
            tracking=tracking,
            registered_model=registered_model,
        )

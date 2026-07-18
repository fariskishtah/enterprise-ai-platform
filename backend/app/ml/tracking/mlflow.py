"""MLflow adapter for logging successful local AI executions."""

from mlflow.tracking import MlflowClient

from app.ml.tracking.base import BaseExperimentTracker
from app.ml.tracking.exceptions import ExperimentTrackingError, TrackingArtifactError
from app.ml.tracking.models import (
    ExperimentRunInfo,
    ExperimentRunRequest,
    ExperimentRunStatus,
    format_tracking_parameter,
)

_MODEL_ARTIFACT_DIRECTORY = "model"


class MLflowExperimentTracker(BaseExperimentTracker):
    """Log completed executions through one explicitly configured MLflow client."""

    def __init__(self, *, tracking_uri: str) -> None:
        if not tracking_uri.strip():
            raise ValueError("tracking_uri must be non-empty.")
        self._client = MlflowClient(tracking_uri=tracking_uri)

    def log_successful_run(
        self,
        request: ExperimentRunRequest,
    ) -> ExperimentRunInfo:
        """Create, populate, and finish exactly one MLflow run."""
        if not request.artifact.path.is_file():
            raise TrackingArtifactError(
                "The completed local model artifact is not available for tracking.",
            )

        run_id: str | None = None
        try:
            experiment_id = self._ensure_experiment(request.experiment_name)
            tags = {
                **request.tags,
                "algorithm": request.key.algorithm.value,
                "task_type": request.key.task_type.value,
                "platform_component": "ai_core",
                "model_format": request.artifact.format.value,
            }
            if request.run_name is not None:
                tags["mlflow.runName"] = request.run_name

            run = self._client.create_run(experiment_id=experiment_id, tags=tags)
            run_id = str(run.info.run_id)
            for name, value in request.parameters.items():
                self._client.log_param(
                    run_id,
                    name,
                    format_tracking_parameter(value),
                )
            for name, value in request.metrics.items():
                self._client.log_metric(run_id, name, value)
            self._client.log_artifact(
                run_id,
                str(request.artifact.path),
                artifact_path=_MODEL_ARTIFACT_DIRECTORY,
            )
            self._client.set_terminated(
                run_id, status=ExperimentRunStatus.FINISHED.value
            )
        except Exception as exc:
            if run_id is not None:
                self._terminate_failed_run(run_id, original_error=exc)
            raise ExperimentTrackingError(
                "MLflow could not log the completed AI Core execution.",
            ) from exc

        run_artifact_uri = str(run.info.artifact_uri).rstrip("/")
        artifact_uri = (
            f"{run_artifact_uri}/{_MODEL_ARTIFACT_DIRECTORY}/"
            f"{request.artifact.path.name}"
        )
        return ExperimentRunInfo(
            experiment_id=experiment_id,
            run_id=run_id,
            artifact_uri=artifact_uri,
            status=ExperimentRunStatus.FINISHED,
        )

    def _ensure_experiment(self, experiment_name: str) -> str:
        existing = self._client.get_experiment_by_name(experiment_name)
        if existing is not None:
            return str(existing.experiment_id)
        return str(self._client.create_experiment(experiment_name))

    def _terminate_failed_run(
        self,
        run_id: str,
        *,
        original_error: Exception,
    ) -> None:
        try:
            self._client.set_terminated(run_id, status="FAILED")
        except Exception as termination_error:
            failures = ExceptionGroup(
                "MLflow logging and failed-run termination both failed.",
                [original_error, termination_error],
            )
            raise ExperimentTrackingError(
                "MLflow could not close the failed AI Core run.",
            ) from failures

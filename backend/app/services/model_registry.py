"""Model registry abstractions and MLflow adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol
from uuid import UUID

from mlflow.tracking import MlflowClient

from app.models.mlops import TrainingRunStatus


class ModelRegistry(Protocol):
    """Model registry port used by MLOps application services."""

    def ensure_experiment(
        self,
        *,
        name: str,
        description: str | None,
    ) -> str:
        """Ensure an external experiment exists and return its registry ID."""

    def create_training_run(
        self,
        *,
        experiment_name: str,
        training_run_id: UUID,
        dataset_version: str,
        algorithm: str,
        parameters: dict[str, object],
        metrics: dict[str, float],
        status: TrainingRunStatus,
    ) -> str:
        """Create external training-run metadata and return the registry run ID."""

    def register_model_artifact(
        self,
        *,
        experiment_name: str,
        training_run_id: UUID,
        model_artifact_id: UUID,
        framework: str,
        model_type: str,
        version: str,
        artifact_path: str,
        checksum: str,
    ) -> None:
        """Register external model artifact metadata."""


class MLflowModelRegistry:
    """MLflow-backed model registry adapter."""

    def __init__(self, *, tracking_uri: str, artifact_root: Path | str) -> None:
        self._tracking_uri = tracking_uri
        self._artifact_root = Path(artifact_root)
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._client = MlflowClient(tracking_uri=tracking_uri)

    def ensure_experiment(
        self,
        *,
        name: str,
        description: str | None,
    ) -> str:
        """Ensure an MLflow experiment exists and return its experiment ID."""
        existing_experiment = self._client.get_experiment_by_name(name)
        if existing_experiment is not None:
            experiment_id = str(existing_experiment.experiment_id)
        else:
            experiment_id = str(
                self._client.create_experiment(
                    name,
                    artifact_location=self._artifact_location(name),
                ),
            )
        if description is not None:
            self._client.set_experiment_tag(
                experiment_id,
                "platform.description",
                description,
            )
        return experiment_id

    def create_training_run(
        self,
        *,
        experiment_name: str,
        training_run_id: UUID,
        dataset_version: str,
        algorithm: str,
        parameters: dict[str, object],
        metrics: dict[str, float],
        status: TrainingRunStatus,
    ) -> str:
        """Create MLflow run metadata for a platform training run."""
        experiment_id = self.ensure_experiment(
            name=experiment_name,
            description=None,
        )
        run = self._client.create_run(
            experiment_id=experiment_id,
            tags={
                "platform_training_run_id": str(training_run_id),
                "platform_dataset_version": dataset_version,
                "platform_algorithm": algorithm,
                "platform_status": status.value,
            },
        )
        run_id = str(run.info.run_id)
        for key, value in parameters.items():
            self._client.log_param(run_id, key, self._serialize_parameter(value))
        for key, value in metrics.items():
            self._client.log_metric(run_id, key, value)

        terminal_status = self._mlflow_terminal_status(status)
        if terminal_status is not None:
            self._client.set_terminated(run_id, status=terminal_status)
        return run_id

    def register_model_artifact(
        self,
        *,
        experiment_name: str,
        training_run_id: UUID,
        model_artifact_id: UUID,
        framework: str,
        model_type: str,
        version: str,
        artifact_path: str,
        checksum: str,
    ) -> None:
        """Register model artifact metadata as MLflow run tags."""
        experiment_id = self.ensure_experiment(
            name=experiment_name,
            description=None,
        )
        runs = self._client.search_runs(
            experiment_ids=[experiment_id],
            filter_string=(f"tags.platform_training_run_id = '{str(training_run_id)}'"),
            max_results=1,
        )
        if not runs:
            return
        run_id = str(runs[0].info.run_id)
        artifact_prefix = f"platform_artifact_{str(model_artifact_id)}"
        self._client.set_tag(run_id, f"{artifact_prefix}_framework", framework)
        self._client.set_tag(run_id, f"{artifact_prefix}_model_type", model_type)
        self._client.set_tag(run_id, f"{artifact_prefix}_version", version)
        self._client.set_tag(run_id, f"{artifact_prefix}_path", artifact_path)
        self._client.set_tag(run_id, f"{artifact_prefix}_checksum", checksum)

    def _artifact_location(self, experiment_name: str) -> str:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", experiment_name).strip("-")
        experiment_dir = self._artifact_root / (safe_name or "experiment")
        experiment_dir.mkdir(parents=True, exist_ok=True)
        return experiment_dir.resolve().as_uri()

    def _serialize_parameter(self, value: object) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True)

    def _mlflow_terminal_status(self, status: TrainingRunStatus) -> str | None:
        return {
            TrainingRunStatus.COMPLETED: "FINISHED",
            TrainingRunStatus.FAILED: "FAILED",
            TrainingRunStatus.CANCELED: "KILLED",
        }.get(status)

"""MLOps experiment management application service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.models.mlops import Experiment, ModelArtifact, TrainingRun, TrainingRunStatus
from app.repositories.mlops import MLOpsRepository, Page
from app.schemas.common import SortOrder
from app.schemas.mlops import (
    ExperimentSortField,
    ModelArtifactSortField,
    TrainingRunSortField,
)
from app.services.exceptions import (
    DuplicateExperimentNameError,
    DuplicateModelArtifactVersionError,
    InvalidTrainingRunError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)
from app.services.model_registry import ModelRegistry
from app.utils.json_validation import ensure_json_serializable
from app.utils.security import as_utc, utc_now


class MLOpsService:
    """Application use cases for experiments, runs, and artifacts."""

    def __init__(
        self,
        *,
        repository: MLOpsRepository,
        model_registry: ModelRegistry,
    ) -> None:
        self._repository = repository
        self._model_registry = model_registry

    async def create_experiment(
        self,
        *,
        name: str,
        description: str | None,
        created_by: UUID,
    ) -> Experiment:
        """Create a unique experiment and sync it to the model registry."""
        existing_experiment = await self._repository.get_experiment_by_name(name)
        if existing_experiment is not None:
            raise DuplicateExperimentNameError("Experiment name is already in use.")
        try:
            experiment = await self._repository.create_experiment(
                name=name,
                description=description,
                created_by=created_by,
            )
            self._model_registry.ensure_experiment(
                name=experiment.name,
                description=experiment.description,
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateExperimentNameError(
                "Experiment name is already in use.",
            ) from exc
        except Exception:
            await self._repository.rollback()
            raise
        return experiment

    async def list_experiments(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None,
        created_by: UUID | None,
        sort_by: ExperimentSortField,
        sort_order: SortOrder,
    ) -> Page[Experiment]:
        """Return paginated experiments."""
        return await self._repository.list_experiments(
            limit=limit,
            offset=offset,
            search=search,
            created_by=created_by,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_experiment(self, experiment_id: UUID) -> Experiment:
        """Return an experiment by ID."""
        experiment = await self._repository.get_experiment_by_id(experiment_id)
        if experiment is None:
            raise ResourceNotFoundError("Experiment not found.")
        return experiment

    async def create_training_run(
        self,
        *,
        experiment_id: UUID,
        dataset_version: str,
        algorithm: str,
        parameters: dict[str, object],
        metrics: dict[str, float],
        status: TrainingRunStatus,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> TrainingRun:
        """Create a training-run metadata record without training a model."""
        ensure_json_serializable(parameters, field_name="parameters")
        ensure_json_serializable(metrics, field_name="metrics")
        experiment = await self._require_experiment(experiment_id)
        normalized_started_at = as_utc(started_at) if started_at else utc_now()
        normalized_finished_at = as_utc(finished_at) if finished_at else None
        if (
            normalized_finished_at is not None
            and normalized_finished_at < normalized_started_at
        ):
            raise InvalidTrainingRunError(
                "finished_at must be greater than or equal to started_at.",
            )

        try:
            training_run = await self._repository.create_training_run(
                experiment_id=experiment.id,
                dataset_version=dataset_version,
                algorithm=algorithm,
                parameters=parameters,
                metrics=metrics,
                status=status,
                started_at=normalized_started_at,
                finished_at=normalized_finished_at,
            )
            self._model_registry.create_training_run(
                experiment_name=experiment.name,
                training_run_id=training_run.id,
                dataset_version=training_run.dataset_version,
                algorithm=training_run.algorithm,
                parameters=training_run.parameters,
                metrics=training_run.metrics,
                status=training_run.status,
            )
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return training_run

    async def list_training_runs(
        self,
        *,
        limit: int,
        offset: int,
        experiment_id: UUID | None,
        dataset_version: str | None,
        algorithm: str | None,
        status: TrainingRunStatus | None,
        sort_by: TrainingRunSortField,
        sort_order: SortOrder,
    ) -> Page[TrainingRun]:
        """Return paginated training runs."""
        return await self._repository.list_training_runs(
            limit=limit,
            offset=offset,
            experiment_id=experiment_id,
            dataset_version=dataset_version,
            algorithm=algorithm,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_training_run(self, training_run_id: UUID) -> TrainingRun:
        """Return a training run by ID."""
        training_run = await self._repository.get_training_run_by_id(training_run_id)
        if training_run is None:
            raise ResourceNotFoundError("Training run not found.")
        return training_run

    async def create_model_artifact(
        self,
        *,
        training_run_id: UUID,
        framework: str,
        model_type: str,
        version: str,
        artifact_path: str,
        checksum: str,
    ) -> ModelArtifact:
        """Register model artifact metadata for a training run."""
        training_run = await self._require_training_run(training_run_id)
        experiment = await self._require_experiment(training_run.experiment_id)
        existing_artifact = (
            await self._repository.get_model_artifact_by_training_run_version(
                training_run_id=training_run_id,
                version=version,
            )
        )
        if existing_artifact is not None:
            raise DuplicateModelArtifactVersionError(
                "Model artifact version is already registered for this run.",
            )

        try:
            model_artifact = await self._repository.create_model_artifact(
                training_run_id=training_run_id,
                framework=framework,
                model_type=model_type,
                version=version,
                artifact_path=artifact_path,
                checksum=checksum,
            )
            self._model_registry.register_model_artifact(
                experiment_name=experiment.name,
                training_run_id=training_run.id,
                model_artifact_id=model_artifact.id,
                framework=model_artifact.framework,
                model_type=model_artifact.model_type,
                version=model_artifact.version,
                artifact_path=model_artifact.artifact_path,
                checksum=model_artifact.checksum,
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateModelArtifactVersionError(
                "Model artifact version or path is already registered.",
            ) from exc
        except Exception:
            await self._repository.rollback()
            raise
        return model_artifact

    async def list_model_artifacts(
        self,
        *,
        limit: int,
        offset: int,
        training_run_id: UUID | None,
        framework: str | None,
        model_type: str | None,
        version: str | None,
        sort_by: ModelArtifactSortField,
        sort_order: SortOrder,
    ) -> Page[ModelArtifact]:
        """Return paginated model artifacts."""
        return await self._repository.list_model_artifacts(
            limit=limit,
            offset=offset,
            training_run_id=training_run_id,
            framework=framework,
            model_type=model_type,
            version=version,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_model_artifact(self, model_artifact_id: UUID) -> ModelArtifact:
        """Return a model artifact by ID."""
        model_artifact = await self._repository.get_model_artifact_by_id(
            model_artifact_id,
        )
        if model_artifact is None:
            raise ResourceNotFoundError("Model artifact not found.")
        return model_artifact

    async def _require_experiment(self, experiment_id: UUID) -> Experiment:
        experiment = await self._repository.get_experiment_by_id(experiment_id)
        if experiment is None:
            raise RelatedResourceNotFoundError("Experiment does not exist.")
        return experiment

    async def _require_training_run(self, training_run_id: UUID) -> TrainingRun:
        training_run = await self._repository.get_training_run_by_id(training_run_id)
        if training_run is None:
            raise RelatedResourceNotFoundError("Training run does not exist.")
        return training_run

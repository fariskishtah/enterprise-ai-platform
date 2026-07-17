"""Persistence adapter for MLOps experiment management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models.mlops import Experiment, ModelArtifact, TrainingRun, TrainingRunStatus
from app.schemas.common import SortOrder
from app.schemas.mlops import (
    ExperimentSortField,
    ModelArtifactSortField,
    TrainingRunSortField,
)

T = TypeVar("T", Experiment, TrainingRun, ModelArtifact)


@dataclass(frozen=True)
class Page[T: Experiment | TrainingRun | ModelArtifact]:
    """Paginated repository result."""

    items: list[T]
    total: int


class MLOpsRepository:
    """Repository for experiments, training runs, and model artifacts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_experiment(
        self,
        *,
        name: str,
        description: str | None,
        created_by: UUID,
    ) -> Experiment:
        """Create an experiment."""
        experiment = Experiment(
            name=name,
            description=description,
            created_by=created_by,
        )
        self._session.add(experiment)
        await self._session.flush()
        await self._session.refresh(experiment)
        return experiment

    async def get_experiment_by_id(self, experiment_id: UUID) -> Experiment | None:
        """Return an experiment by ID."""
        statement = select(Experiment).where(Experiment.id == experiment_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_experiment_by_name(self, name: str) -> Experiment | None:
        """Return an experiment by exact name."""
        statement = select(Experiment).where(Experiment.name == name)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

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
        statement = select(Experiment)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Experiment.name.ilike(pattern),
                    Experiment.description.ilike(pattern),
                ),
            )
        if created_by is not None:
            statement = statement.where(Experiment.created_by == created_by)
        return await self._paginate(
            statement=statement,
            model=Experiment,
            sort_column=self._experiment_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def create_training_run(
        self,
        *,
        experiment_id: UUID,
        dataset_version: str,
        algorithm: str,
        parameters: dict[str, object],
        metrics: dict[str, float],
        status: TrainingRunStatus,
        started_at: datetime,
        finished_at: datetime | None,
    ) -> TrainingRun:
        """Create a training run record."""
        training_run = TrainingRun(
            experiment_id=experiment_id,
            dataset_version=dataset_version,
            algorithm=algorithm,
            parameters=parameters,
            metrics=metrics,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )
        self._session.add(training_run)
        await self._session.flush()
        await self._session.refresh(training_run)
        return training_run

    async def get_training_run_by_id(
        self,
        training_run_id: UUID,
    ) -> TrainingRun | None:
        """Return a training run by ID."""
        statement = select(TrainingRun).where(TrainingRun.id == training_run_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

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
        statement = select(TrainingRun)
        if experiment_id is not None:
            statement = statement.where(TrainingRun.experiment_id == experiment_id)
        if dataset_version is not None:
            statement = statement.where(TrainingRun.dataset_version == dataset_version)
        if algorithm is not None:
            statement = statement.where(TrainingRun.algorithm == algorithm)
        if status is not None:
            statement = statement.where(TrainingRun.status == status)
        return await self._paginate(
            statement=statement,
            model=TrainingRun,
            sort_column=self._training_run_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

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
        """Create a model artifact record."""
        model_artifact = ModelArtifact(
            training_run_id=training_run_id,
            framework=framework,
            model_type=model_type,
            version=version,
            artifact_path=artifact_path,
            checksum=checksum,
        )
        self._session.add(model_artifact)
        await self._session.flush()
        await self._session.refresh(model_artifact)
        return model_artifact

    async def get_model_artifact_by_id(
        self,
        model_artifact_id: UUID,
    ) -> ModelArtifact | None:
        """Return a model artifact by ID."""
        statement = select(ModelArtifact).where(ModelArtifact.id == model_artifact_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_model_artifact_by_training_run_version(
        self,
        *,
        training_run_id: UUID,
        version: str,
    ) -> ModelArtifact | None:
        """Return an artifact by training run and version."""
        statement = select(ModelArtifact).where(
            ModelArtifact.training_run_id == training_run_id,
            ModelArtifact.version == version,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

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
        statement = select(ModelArtifact)
        if training_run_id is not None:
            statement = statement.where(
                ModelArtifact.training_run_id == training_run_id,
            )
        if framework is not None:
            statement = statement.where(ModelArtifact.framework == framework)
        if model_type is not None:
            statement = statement.where(ModelArtifact.model_type == model_type)
        if version is not None:
            statement = statement.where(ModelArtifact.version == version)
        return await self._paginate(
            statement=statement,
            model=ModelArtifact,
            sort_column=self._model_artifact_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def commit(self) -> None:
        """Commit the active transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active transaction."""
        await self._session.rollback()

    async def refresh(
        self,
        entity: Experiment | TrainingRun | ModelArtifact,
    ) -> None:
        """Refresh an entity from the database."""
        await self._session.refresh(entity)

    async def _paginate(
        self,
        *,
        statement: Select[tuple[T]],
        model: type[T],
        sort_column: ColumnElement[object],
        sort_order: SortOrder,
        limit: int,
        offset: int,
    ) -> Page[T]:
        count_statement = select(func.count()).select_from(
            statement.order_by(None).subquery(),
        )
        total = await self._session.scalar(count_statement)
        ordered_column = (
            sort_column.desc() if sort_order == SortOrder.DESC else sort_column.asc()
        )
        paginated_statement = (
            statement.order_by(
                ordered_column,
                model.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(paginated_statement)
        return Page(items=list(result.scalars().all()), total=total or 0)

    def _experiment_sort_column(
        self,
        sort_by: ExperimentSortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                ExperimentSortField.NAME: Experiment.name,
                ExperimentSortField.CREATED_AT: Experiment.created_at,
            }[sort_by],
        )

    def _training_run_sort_column(
        self,
        sort_by: TrainingRunSortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                TrainingRunSortField.STARTED_AT: TrainingRun.started_at,
                TrainingRunSortField.FINISHED_AT: TrainingRun.finished_at,
                TrainingRunSortField.DATASET_VERSION: TrainingRun.dataset_version,
                TrainingRunSortField.ALGORITHM: TrainingRun.algorithm,
                TrainingRunSortField.STATUS: TrainingRun.status,
            }[sort_by],
        )

    def _model_artifact_sort_column(
        self,
        sort_by: ModelArtifactSortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                ModelArtifactSortField.FRAMEWORK: ModelArtifact.framework,
                ModelArtifactSortField.MODEL_TYPE: ModelArtifact.model_type,
                ModelArtifactSortField.VERSION: ModelArtifact.version,
            }[sort_by],
        )

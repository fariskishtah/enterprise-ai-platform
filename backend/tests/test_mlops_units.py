"""MLOps repository and service tests."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.models.mlops import TrainingRunStatus
from app.models.user import UserRole
from app.repositories.mlops import MLOpsRepository
from app.repositories.users import UserRepository
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
)
from app.services.mlops import MLOpsService
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VALID_PASSWORD = "ValidPassword1!"


@dataclass
class FakeModelRegistry:
    """In-memory model registry test double."""

    experiments: list[str] = field(default_factory=list)
    training_runs: list[UUID] = field(default_factory=list)
    model_artifacts: list[UUID] = field(default_factory=list)

    def ensure_experiment(
        self,
        *,
        name: str,
        description: str | None,
    ) -> str:
        self.experiments.append(name)
        return f"experiment:{name}:{description or ''}"

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
        self.training_runs.append(training_run_id)
        return (
            f"run:{experiment_name}:{dataset_version}:{algorithm}:"
            f"{len(parameters)}:{len(metrics)}:{status.value}"
        )

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
        _ = (
            experiment_name,
            training_run_id,
            framework,
            model_type,
            version,
            artifact_path,
            checksum,
        )
        self.model_artifacts.append(model_artifact_id)


async def create_user_id(
    session: AsyncSession,
    *,
    email: str = "mlops-user@example.com",
) -> UUID:
    """Create a user and return its ID."""
    service = UserService(
        repository=UserRepository(session),
        password_hasher=PasswordHasher(),
    )
    user = await service.create_user(
        email=email,
        password=VALID_PASSWORD,
        role=UserRole.ADMIN,
    )
    return user.id


def mlops_service(
    session: AsyncSession,
    registry: FakeModelRegistry,
) -> MLOpsService:
    """Build an MLOps service for tests."""
    return MLOpsService(
        repository=MLOpsRepository(session),
        model_registry=registry,
    )


@pytest.mark.anyio
async def test_repository_creates_lists_runs_and_artifacts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repository persists and lists the Sprint 8 MLOps entities."""
    async with session_factory() as session:
        created_by = await create_user_id(session)
        repository = MLOpsRepository(session)
        experiment = await repository.create_experiment(
            name="Baseline Quality Experiment",
            description="Quality baseline",
            created_by=created_by,
        )
        training_run = await repository.create_training_run(
            experiment_id=experiment.id,
            dataset_version="dataset_v1",
            algorithm="baseline-regressor",
            parameters={"window_size": 5},
            metrics={"rmse": 1.25},
            status=TrainingRunStatus.PENDING,
            started_at=datetime.now(UTC),
            finished_at=None,
        )
        artifact = await repository.create_model_artifact(
            training_run_id=training_run.id,
            framework="sklearn",
            model_type="metadata-only",
            version="v1",
            artifact_path="s3://models/baseline/v1/model.pkl",
            checksum="a" * 64,
        )
        await repository.commit()

        experiments = await repository.list_experiments(
            limit=20,
            offset=0,
            search="quality",
            created_by=created_by,
            sort_by=ExperimentSortField.CREATED_AT,
            sort_order=SortOrder.DESC,
        )
        training_runs = await repository.list_training_runs(
            limit=20,
            offset=0,
            experiment_id=experiment.id,
            dataset_version="dataset_v1",
            algorithm="baseline-regressor",
            status=TrainingRunStatus.PENDING,
            sort_by=TrainingRunSortField.STARTED_AT,
            sort_order=SortOrder.DESC,
        )
        artifacts = await repository.list_model_artifacts(
            limit=20,
            offset=0,
            training_run_id=training_run.id,
            framework="sklearn",
            model_type="metadata-only",
            version="v1",
            sort_by=ModelArtifactSortField.VERSION,
            sort_order=SortOrder.DESC,
        )

        assert experiments.total == 1
        assert training_runs.items[0].id == training_run.id
        assert artifacts.items[0].id == artifact.id


@pytest.mark.anyio
async def test_service_rejects_duplicate_experiment_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Experiment names are unique."""
    async with session_factory() as session:
        registry = FakeModelRegistry()
        service = mlops_service(session, registry)
        created_by = await create_user_id(session)
        await service.create_experiment(
            name="Unique Experiment",
            description=None,
            created_by=created_by,
        )

        with pytest.raises(DuplicateExperimentNameError):
            await service.create_experiment(
                name="Unique Experiment",
                description=None,
                created_by=created_by,
            )


@pytest.mark.anyio
async def test_service_creates_training_run_and_registers_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Training-run creation records metadata in the model registry."""
    async with session_factory() as session:
        registry = FakeModelRegistry()
        service = mlops_service(session, registry)
        created_by = await create_user_id(session)
        experiment = await service.create_experiment(
            name="Registry Experiment",
            description=None,
            created_by=created_by,
        )

        training_run = await service.create_training_run(
            experiment_id=experiment.id,
            dataset_version="dataset_v2",
            algorithm="baseline-regressor",
            parameters={"rolling_window": 5},
            metrics={"mae": 0.4},
            status=TrainingRunStatus.PENDING,
            started_at=None,
            finished_at=None,
        )

        assert training_run.id in registry.training_runs
        assert training_run.parameters["rolling_window"] == 5


@pytest.mark.anyio
async def test_service_validates_training_run_parent_and_timestamps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Training runs require an experiment and valid time ordering."""
    async with session_factory() as session:
        registry = FakeModelRegistry()
        service = mlops_service(session, registry)

        with pytest.raises(RelatedResourceNotFoundError):
            await service.create_training_run(
                experiment_id=uuid4(),
                dataset_version="dataset_v1",
                algorithm="baseline-regressor",
                parameters={},
                metrics={},
                status=TrainingRunStatus.PENDING,
                started_at=None,
                finished_at=None,
            )

        created_by = await create_user_id(session)
        experiment = await service.create_experiment(
            name="Timestamp Experiment",
            description=None,
            created_by=created_by,
        )
        started_at = datetime.now(UTC)

        with pytest.raises(InvalidTrainingRunError):
            await service.create_training_run(
                experiment_id=experiment.id,
                dataset_version="dataset_v1",
                algorithm="baseline-regressor",
                parameters={},
                metrics={},
                status=TrainingRunStatus.COMPLETED,
                started_at=started_at,
                finished_at=started_at - timedelta(minutes=1),
            )


@pytest.mark.anyio
async def test_service_registers_artifact_and_rejects_duplicate_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Model artifacts are unique by training run and version."""
    async with session_factory() as session:
        registry = FakeModelRegistry()
        service = mlops_service(session, registry)
        created_by = await create_user_id(session)
        experiment = await service.create_experiment(
            name="Artifact Experiment",
            description=None,
            created_by=created_by,
        )
        training_run = await service.create_training_run(
            experiment_id=experiment.id,
            dataset_version="dataset_v1",
            algorithm="baseline-regressor",
            parameters={},
            metrics={},
            status=TrainingRunStatus.PENDING,
            started_at=None,
            finished_at=None,
        )
        artifact = await service.create_model_artifact(
            training_run_id=training_run.id,
            framework="sklearn",
            model_type="metadata-only",
            version="v1",
            artifact_path="s3://models/artifact/v1/model.pkl",
            checksum="b" * 64,
        )

        with pytest.raises(DuplicateModelArtifactVersionError):
            await service.create_model_artifact(
                training_run_id=training_run.id,
                framework="sklearn",
                model_type="metadata-only",
                version="v1",
                artifact_path="s3://models/artifact/v1/other.pkl",
                checksum="c" * 64,
            )

        assert artifact.id in registry.model_artifacts

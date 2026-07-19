"""Persistent training-job contracts, service, repository, and worker tests."""

from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import app.ml.jobs.service as training_job_service_module
import numpy as np
import pytest
from app.ml.base import TrainerInput
from app.ml.composition import create_random_forest_regression_prediction_plan
from app.ml.domain import TaskType
from app.ml.jobs import (
    RandomForestRegressionJobSpec,
    TrainingJobConflictError,
    TrainingJobEnqueueError,
    TrainingJobQueuePersistenceError,
    TrainingJobRecord,
    TrainingJobSpec,
    TrainingJobStatus,
    random_forest_key,
)
from app.ml.jobs.service import StaleTrainingJobRecoveryService, TrainingJobService
from app.ml.jobs.worker import (
    BackgroundTrainingOutcome,
    TrainingJobWorker,
    WorkerExecutionState,
)
from app.ml.monitoring import (
    ModelReferenceProfile,
    build_model_reference_profile_draft,
)
from app.ml.monitoring.reconcile import (
    reconcile_reference_profile_candidates,
)
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    ModelRegistryError,
    RegisteredModelVersion,
    RegisteredModelVersionStatus,
)
from app.ml.services import (
    BaseRegisteredModelLoader,
    PredictionService,
    RegisteredPredictionRequest,
)
from app.ml.trainers.random_forest import RandomForestRegressorTrainer
from app.ml.trainers.random_forest.types import (
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
)
from app.models.ai_monitoring import ModelReferenceProfileEntity
from app.models.user import User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.utils.security import utc_now
from pydantic import ValidationError
from sklearn.ensemble import RandomForestRegressor  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FakeQueue:
    """Record UUID-only queue messages without a Redis service."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.job_ids: list[UUID] = []

    def enqueue(self, training_job_id: UUID) -> str:
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.job_ids.append(training_job_id)
        return f"message-{training_job_id}"


class QueueIdentifierFailingRepository(TrainingJobRepository):
    """Fail only the post-enqueue broker-identifier write."""

    async def set_queue_identifier(
        self,
        *,
        job_id: UUID,
        queue_message_id: str,
        expected_version: int,
    ) -> TrainingJobRecord | None:
        _ = (job_id, queue_message_id, expected_version)
        raise RuntimeError("database write failed")


class ExistingVersionRegistry(BaseModelRegistry):
    """Resolve one checkpointed version and reject any new registration."""

    def __init__(self, version: RegisteredModelVersion) -> None:
        self.version = version
        self.resolve_count = 0
        self.registration_attempt_count = 0

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        _ = request
        self.registration_attempt_count += 1
        raise AssertionError("Reconciliation must not register another model version.")

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        assert registered_model_name == self.version.registered_model_name
        assert version_or_alias == self.version.version
        self.resolve_count += 1
        return self.version


class ExistingVersionLoader(BaseRegisteredModelLoader):
    """Load the fitted model already attached to the checkpointed version."""

    def __init__(
        self, model: RandomForestRegressor, *, unavailable: bool = False
    ) -> None:
        self.model = model
        self.unavailable = unavailable
        self.load_count = 0

    def load[
        ModelT
    ](
        self,
        model_version: RegisteredModelVersion,
        expected_type: type[ModelT],
    ) -> ModelT:
        _ = model_version
        self.load_count += 1
        if self.unavailable:
            raise OSError("model loader unavailable")
        assert isinstance(self.model, expected_type)
        return self.model


def _specification(*, seed: int = 11) -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,), (3.0,)),
        training_targets=(0.0, 1.0, 2.0, 3.0),
        evaluation_features=((0.5,), (2.5,)),
        evaluation_targets=(0.5, 2.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        random_seed=seed,
        experiment_name="Background Regression",
        run_name="job-test",
        registered_model_name="ai_core_random_forest_regression",
        tags={"purpose": "job-test"},
    )


async def _user_id(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
) -> UUID:
    user = User(
        email=email,
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user.id


def test_job_specification_is_immutable_validated_and_deterministic() -> None:
    """Persisted requests are typed JSON data rather than arbitrary dictionaries."""
    specification = _specification()

    assert specification.fingerprint() == _specification().fingerprint()
    assert specification.payload()["training_features"] == [
        [0.0],
        [1.0],
        [2.0],
        [3.0],
    ]
    with pytest.raises(ValidationError):
        RandomForestRegressionJobSpec.model_validate(
            {**specification.payload(), "training_features": [[True], [1.0]]},
        )
    with pytest.raises(ValidationError):
        RandomForestRegressionJobSpec.model_validate(
            {**specification.payload(), "training_targets": [1.0]},
        )
    with pytest.raises(ValidationError):
        _set_attribute(specification, "random_seed", 99)


@pytest.mark.anyio
async def test_submission_persists_before_enqueue_and_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Equivalent scoped retries return one durable job and one queue message."""
    metric_labels: list[dict[str, str]] = []
    monkeypatch.setattr(
        training_job_service_module,
        "record_training_job_submitted",
        lambda **labels: metric_labels.append(labels),
    )
    requested_by = await _user_id(session_factory, email="job-submit@example.com")
    queue = FakeQueue()
    async with session_factory() as session:
        service = TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=queue,
            max_attempts=3,
        )
        first = await service.submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key="stable-request",
        )
        second = await service.submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key="stable-request",
        )

    assert first.created is True
    assert second.created is False
    assert second.job.id == first.job.id
    assert second.job.queue_message_id == f"message-{first.job.id}"
    assert metric_labels == [{"task_type": "regression", "algorithm": "random_forest"}]
    assert queue.job_ids == [first.job.id]


@pytest.mark.anyio
async def test_idempotency_conflict_and_enqueue_failure_are_honest(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Changed payloads conflict and broker failures persist a safe terminal job."""
    requested_by = await _user_id(session_factory, email="job-failure@example.com")
    async with session_factory() as session:
        service = TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=FakeQueue(),
            max_attempts=3,
        )
        first = await service.submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key="conflict-key",
        )
        with pytest.raises(TrainingJobConflictError, match="different request"):
            await service.submit(
                requested_by_user_id=requested_by,
                key=random_forest_key(TaskType.REGRESSION),
                specification=_specification(seed=12),
                idempotency_key="conflict-key",
            )

    async with session_factory() as session:
        failing_service = TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=FakeQueue(fail=True),
            max_attempts=3,
        )
        with pytest.raises(TrainingJobEnqueueError):
            await failing_service.submit(
                requested_by_user_id=requested_by,
                key=random_forest_key(TaskType.REGRESSION),
                specification=_specification(),
                idempotency_key="enqueue-failure",
            )
        page = await TrainingJobRepository(session).list_jobs(
            requested_by_user_id=requested_by,
            status=TrainingJobStatus.FAILED,
            limit=10,
            offset=0,
        )

    assert first.job.status is TrainingJobStatus.QUEUED
    assert len(page.items) == 1
    assert page.items[0].error_code == "enqueue_failed"
    assert "redis unavailable" not in (page.items[0].safe_error_message or "")


@pytest.mark.anyio
async def test_queue_identifier_failure_returns_error_and_reconciliation_repairs_job(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-enqueued job is recoverable but never reported as normal success."""
    requested_by = await _user_id(
        session_factory,
        email="job-message-persistence@example.com",
    )
    submitted_at = utc_now() - timedelta(minutes=5)
    monkeypatch.setattr(training_job_service_module, "utc_now", lambda: submitted_at)
    initial_queue = FakeQueue()
    async with session_factory() as session:
        service = TrainingJobService(
            repository=QueueIdentifierFailingRepository(session),
            queue=initial_queue,
            max_attempts=3,
        )
        with pytest.raises(TrainingJobQueuePersistenceError):
            await service.submit(
                requested_by_user_id=requested_by,
                key=random_forest_key(TaskType.REGRESSION),
                specification=_specification(),
                idempotency_key="message-persistence",
            )
        with pytest.raises(TrainingJobQueuePersistenceError):
            await service.submit(
                requested_by_user_id=requested_by,
                key=random_forest_key(TaskType.REGRESSION),
                specification=_specification(),
                idempotency_key="message-persistence",
            )
        page = await TrainingJobRepository(session).list_jobs(
            requested_by_user_id=requested_by,
            status=TrainingJobStatus.QUEUED,
            limit=10,
            offset=0,
        )

    assert len(page.items) == 1
    job = page.items[0]
    assert initial_queue.job_ids == [job.id]
    assert job.queue_message_id is None
    assert job.error_code == "queue_message_persistence_pending"

    reconciliation_queue = FakeQueue()
    monkeypatch.setattr(
        training_job_service_module,
        "utc_now",
        lambda: submitted_at + timedelta(minutes=5),
    )
    async with session_factory() as session:
        recovered = await StaleTrainingJobRecoveryService(
            repository=TrainingJobRepository(session),
            queue=reconciliation_queue,
            stale_after_seconds=3600,
            orphaned_after_seconds=60,
        ).reconcile()
        repaired = await TrainingJobRepository(session).get_by_id(job.id)

    assert recovered == (job.id,)
    assert reconciliation_queue.job_ids == [job.id]
    assert repaired is not None
    assert repaired.queue_message_id == f"message-{job.id}"
    assert repaired.error_code is None


@pytest.mark.anyio
async def test_worker_claims_once_checkpoints_and_skips_duplicate_delivery(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Persistent state prevents a second delivery from registering twice."""
    requested_by = await _user_id(session_factory, email="job-worker@example.com")
    queue = FakeQueue()
    async with session_factory() as session:
        submission = await TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=queue,
            max_attempts=3,
        ).submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key=None,
        )

    executions: list[str] = []
    aliases: list[tuple[str, str]] = []

    def execute(specification: TrainingJobSpec) -> BackgroundTrainingOutcome:
        executions.append(specification.registered_model_name)
        return BackgroundTrainingOutcome(
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="experiment-1",
            mlflow_run_id="run-1",
            registered_model_version="1",
            metrics={"rmse": 0.2, "r2": 0.8},
        )

    worker = TrainingJobWorker(
        session_factory=session_factory,
        execute_specification=execute,
        assign_candidate_alias=lambda name, version: aliases.append((name, version)),
    )
    first = await worker.execute(submission.job.id)
    duplicate = await worker.execute(submission.job.id)

    async with session_factory() as session:
        completed = await TrainingJobRepository(session).get_by_id(submission.job.id)

    assert first is WorkerExecutionState.SUCCEEDED
    assert duplicate is WorkerExecutionState.SKIPPED
    assert executions == ["ai_core_random_forest_regression"]
    assert aliases == [("ai_core_random_forest_regression", "1")]
    assert completed is not None
    assert completed.status is TrainingJobStatus.SUCCEEDED
    assert completed.attempt_count == 1
    assert completed.metrics == {"rmse": 0.2, "r2": 0.8}


@pytest.mark.anyio
async def test_profile_failure_after_registration_is_checkpointed_and_reconciled_once(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-alias profile outage degrades monitoring without model duplication."""
    requested_by = await _user_id(
        session_factory,
        email="job-profile-checkpoint@example.com",
    )
    async with session_factory() as session:
        submission = await TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=FakeQueue(),
            max_attempts=3,
        ).submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key=None,
        )

    training_execution_count = 0
    model_registration_count = 0
    alias_assignments: list[tuple[str, str]] = []
    fitted_models: list[RandomForestRegressor] = []

    def execute(specification: TrainingJobSpec) -> BackgroundTrainingOutcome:
        nonlocal training_execution_count, model_registration_count
        assert isinstance(specification, RandomForestRegressionJobSpec)
        training_execution_count += 1
        training_features: FeatureArray = np.asarray(
            specification.training_features,
            dtype=np.float64,
        )
        training_targets: RegressionTargetArray = np.asarray(
            specification.training_targets,
            dtype=np.float64,
        )
        evaluation_features: FeatureArray = np.asarray(
            specification.evaluation_features,
            dtype=np.float64,
        )
        model = (
            RandomForestRegressorTrainer()
            .fit(
                TrainerInput(
                    features=training_features,
                    targets=training_targets,
                    hyperparameters=specification.hyperparameters.model_dump(),
                    random_seed=specification.random_seed,
                ),
            )
            .model
        )
        fitted_models.append(model)
        predictions = cast(
            RegressionPredictionArray, model.predict(evaluation_features)
        )
        model_registration_count += 1
        return BackgroundTrainingOutcome(
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="experiment-profile",
            mlflow_run_id="run-profile",
            registered_model_version="41",
            metrics={"rmse": 0.2, "r2": 0.8},
            reference_profile=build_model_reference_profile_draft(
                registered_model_name=specification.registered_model_name,
                model_version="41",
                key=random_forest_key(TaskType.REGRESSION),
                evaluation_features=evaluation_features,
                predictions=predictions,
                bin_count=10,
                created_at=utc_now(),
            ),
        )

    original_create_profile = PredictionMonitoringRepository.create_reference_profile

    async def fail_profile_persistence(
        _repository: PredictionMonitoringRepository,
        _profile: ModelReferenceProfile,
    ) -> ModelReferenceProfile:
        raise OSError("monitoring database unavailable")

    monkeypatch.setattr(
        PredictionMonitoringRepository,
        "create_reference_profile",
        fail_profile_persistence,
    )
    worker = TrainingJobWorker(
        session_factory=session_factory,
        execute_specification=execute,
        assign_candidate_alias=lambda name, version: alias_assignments.append(
            (name, version),
        ),
    )

    first = await worker.execute(submission.job.id)
    duplicate = await worker.execute(submission.job.id)

    assert first is WorkerExecutionState.SUCCEEDED
    assert duplicate is WorkerExecutionState.SKIPPED
    assert training_execution_count == 1
    assert model_registration_count == 1
    assert alias_assignments == [("ai_core_random_forest_regression", "41")]
    assert len(fitted_models) == 1

    monkeypatch.setattr(
        PredictionMonitoringRepository,
        "create_reference_profile",
        original_create_profile,
    )
    async with session_factory() as session:
        job = await TrainingJobRepository(session).get_by_id(submission.job.id)
        monitoring_repository = PredictionMonitoringRepository(session)
        missing = await monitoring_repository.list_missing_reference_profiles(limit=10)
        absent = await monitoring_repository.get_reference_profile(
            "ai_core_random_forest_regression",
            "41",
        )

    assert job is not None
    assert job.status is TrainingJobStatus.SUCCEEDED
    assert job.registered_model_version == "41"
    assert absent is None
    assert len(missing) == 1
    assert missing[0].registered_model_version == "41"

    version = RegisteredModelVersion(
        registered_model_name="ai_core_random_forest_regression",
        version="41",
        run_id="run-profile",
        source_uri="file:///checkpointed-model.joblib",
        key=random_forest_key(TaskType.REGRESSION),
        status=RegisteredModelVersionStatus.READY,
        aliases=("candidate",),
    )
    registry = ExistingVersionRegistry(version)
    unavailable_loader = ExistingVersionLoader(fitted_models[0], unavailable=True)
    async with session_factory() as session:
        failed_reconciliation = await reconcile_reference_profile_candidates(
            repository=PredictionMonitoringRepository(session),
            candidates=missing,
            prediction_service=PredictionService(
                model_registry=registry,
                model_loader=unavailable_loader,
            ),
            bin_count=10,
        )
        still_missing = await PredictionMonitoringRepository(
            session,
        ).list_missing_reference_profiles(limit=10)

    assert failed_reconciliation.examined == 1
    assert failed_reconciliation.created == 0
    assert failed_reconciliation.failed == 1
    assert len(still_missing) == 1
    assert training_execution_count == 1
    assert model_registration_count == 1
    assert registry.registration_attempt_count == 0

    loader = ExistingVersionLoader(fitted_models[0])
    prediction_service = PredictionService(
        model_registry=registry,
        model_loader=loader,
    )
    usable_result = prediction_service.predict(
        create_random_forest_regression_prediction_plan(),
        RegisteredPredictionRequest(
            "ai_core_random_forest_regression",
            "41",
            np.asarray(((0.5,),), dtype=np.float64),
        ),
    )
    assert usable_result.predictions.shape == (1,)

    async with session_factory() as session:
        monitoring_repository = PredictionMonitoringRepository(session)
        successful_reconciliation = await reconcile_reference_profile_candidates(
            repository=monitoring_repository,
            candidates=still_missing,
            prediction_service=prediction_service,
            bin_count=10,
        )
        no_remaining_candidates = (
            await monitoring_repository.list_missing_reference_profiles(limit=10)
        )
        repeated_reconciliation = await reconcile_reference_profile_candidates(
            repository=monitoring_repository,
            candidates=no_remaining_candidates,
            prediction_service=prediction_service,
            bin_count=10,
        )
        profile_row_count = await session.scalar(
            select(func.count(ModelReferenceProfileEntity.id)),
        )
        profile = await monitoring_repository.get_reference_profile(
            "ai_core_random_forest_regression",
            "41",
        )

    assert successful_reconciliation.created == 1
    assert successful_reconciliation.failed == 0
    assert repeated_reconciliation.examined == 0
    assert repeated_reconciliation.created == 0
    assert no_remaining_candidates == ()
    assert profile_row_count == 1
    assert profile is not None
    assert profile.model_version == "41"
    assert profile.training_job_id == submission.job.id
    assert training_execution_count == 1
    assert model_registration_count == 1
    assert alias_assignments == [("ai_core_random_forest_regression", "41")]
    assert registry.registration_attempt_count == 0


@pytest.mark.anyio
async def test_transient_alias_retry_reuses_checkpointed_registered_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A retry after alias failure does not create a second registered version."""
    requested_by = await _user_id(session_factory, email="job-retry@example.com")
    async with session_factory() as session:
        submission = await TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=FakeQueue(),
            max_attempts=2,
        ).submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key=None,
        )

    executions = 0
    alias_attempts = 0

    def execute(_specification: TrainingJobSpec) -> BackgroundTrainingOutcome:
        nonlocal executions
        executions += 1
        return BackgroundTrainingOutcome(
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="experiment-1",
            mlflow_run_id="run-1",
            registered_model_version="7",
            metrics={"rmse": 0.2, "r2": 0.8},
        )

    def assign_alias(_name: str, _version: str) -> None:
        nonlocal alias_attempts
        alias_attempts += 1
        if alias_attempts == 1:
            raise ModelRegistryError("temporary registry failure")

    worker = TrainingJobWorker(
        session_factory=session_factory,
        execute_specification=execute,
        assign_candidate_alias=assign_alias,
    )
    first = await worker.execute(submission.job.id)
    second = await worker.execute(submission.job.id)

    assert first is WorkerExecutionState.RETRY
    assert second is WorkerExecutionState.SUCCEEDED
    assert executions == 1
    assert alias_attempts == 2


@pytest.mark.anyio
async def test_cancelled_and_deterministic_failed_jobs_do_not_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Queued cancellation and invalid execution both terminate honestly."""
    requested_by = await _user_id(session_factory, email="job-terminal@example.com")
    queue = FakeQueue()
    async with session_factory() as session:
        service = TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=queue,
            max_attempts=3,
        )
        cancelled_submission = await service.submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key="cancelled",
        )
        cancelled = await service.cancel(
            job_id=cancelled_submission.job.id,
            current_user_id=requested_by,
            is_admin=False,
        )
        failed_submission = await service.submit(
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(seed=22),
            idempotency_key="failed",
        )

    worker = TrainingJobWorker(
        session_factory=session_factory,
        execute_specification=lambda _specification: (_raise_invalid()),
        assign_candidate_alias=lambda _name, _version: None,
    )
    cancelled_result = await worker.execute(cancelled.id)
    failed_result = await worker.execute(failed_submission.job.id)

    async with session_factory() as session:
        failed = await TrainingJobRepository(session).get_by_id(
            failed_submission.job.id,
        )

    assert cancelled.status is TrainingJobStatus.CANCELLED
    assert cancelled_result is WorkerExecutionState.SKIPPED
    assert failed_result is WorkerExecutionState.TERMINAL
    assert failed is not None
    assert failed.status is TrainingJobStatus.FAILED
    assert failed.attempt_count == 1
    assert failed.error_code == "training_validation_failed"


def _raise_invalid() -> BackgroundTrainingOutcome:
    raise ValueError("private deterministic details")


def _set_attribute(specification: object, name: str, value: object) -> None:
    setattr(specification, name, value)


@pytest.mark.anyio
async def test_stale_recovery_requeues_available_attempts_and_fails_exhausted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Administrative recovery leaves no expired running claim indefinitely stuck."""
    requested_by = await _user_id(session_factory, email="job-stale@example.com")
    recoverable_id = uuid4()
    exhausted_id = uuid4()
    stale_time = utc_now() - timedelta(hours=2)
    async with session_factory() as session:
        repository = TrainingJobRepository(session)
        for job_id, max_attempts in ((recoverable_id, 2), (exhausted_id, 1)):
            await repository.create(
                job_id=job_id,
                requested_by_user_id=requested_by,
                key=random_forest_key(TaskType.REGRESSION),
                specification=_specification(),
                idempotency_key=None,
                request_fingerprint=_specification().fingerprint(),
                max_attempts=max_attempts,
                queued_at=stale_time,
            )
            claimed = await repository.claim_queued(
                job_id=job_id,
                started_at=stale_time,
            )
            assert claimed is not None
        await repository.commit()

    queue = FakeQueue()
    async with session_factory() as session:
        recovered = await StaleTrainingJobRecoveryService(
            repository=TrainingJobRepository(session),
            queue=queue,
            stale_after_seconds=3600,
            orphaned_after_seconds=60,
        ).reconcile()
        repository = TrainingJobRepository(session)
        recoverable = await repository.get_by_id(recoverable_id)
        exhausted = await repository.get_by_id(exhausted_id)

    assert recovered == (recoverable_id,)
    assert queue.job_ids == [recoverable_id]
    assert recoverable is not None
    assert recoverable.status is TrainingJobStatus.QUEUED
    assert exhausted is not None
    assert exhausted.status is TrainingJobStatus.FAILED
    assert exhausted.error_code == "retry_exhausted"


@pytest.mark.anyio
async def test_orphan_reconciliation_recovers_crash_once_and_ignores_recent_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-requeue crash is repaired once after age gating, without early races."""
    requested_by = await _user_id(session_factory, email="job-orphan@example.com")
    crashed_id = uuid4()
    recent_id = uuid4()
    now = utc_now()
    stale_time = now - timedelta(hours=2)
    async with session_factory() as session:
        repository = TrainingJobRepository(session)
        await repository.create(
            job_id=crashed_id,
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key=None,
            request_fingerprint=_specification().fingerprint(),
            max_attempts=3,
            queued_at=stale_time,
        )
        claimed = await repository.claim_queued(
            job_id=crashed_id,
            started_at=stale_time,
        )
        assert claimed is not None
        requeued = await repository.requeue_stale(
            stale_before=now - timedelta(hours=1),
            queued_at=now - timedelta(minutes=2),
        )
        assert requeued == (crashed_id,)
        await repository.create(
            job_id=recent_id,
            requested_by_user_id=requested_by,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(seed=12),
            idempotency_key=None,
            request_fingerprint=_specification(seed=12).fingerprint(),
            max_attempts=3,
            queued_at=now,
        )
        await repository.commit()

    monkeypatch.setattr(training_job_service_module, "utc_now", lambda: now)
    queue = FakeQueue()
    async with session_factory() as session:
        service = StaleTrainingJobRecoveryService(
            repository=TrainingJobRepository(session),
            queue=queue,
            stale_after_seconds=3600,
            orphaned_after_seconds=60,
        )
        first = await service.reconcile()
        second = await service.reconcile()
        recent = await TrainingJobRepository(session).get_by_id(recent_id)

    assert first == (crashed_id,)
    assert second == ()
    assert queue.job_ids == [crashed_id]
    assert recent is not None
    assert recent.queue_message_id is None

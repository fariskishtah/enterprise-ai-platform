"""Real local training, MLflow registration, and retraining completion smoke test."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from app.config.settings import Settings
from app.ml.composition import (
    create_ai_model_registry,
    create_ai_tracked_training_service,
)
from app.ml.domain import TaskType
from app.ml.jobs import TrainingJobStatus, random_forest_key
from app.ml.jobs.service import TrainingJobService
from app.ml.jobs.worker import (
    TrainingJobWorker,
    WorkerExecutionState,
    execute_tracked_training_specification,
)
from app.ml.monitoring import DriftSeverity
from app.ml.retraining import (
    RetrainingPolicyEvaluator,
    RetrainingRequestStatus,
    RetrainingTriggerType,
)
from app.ml.retraining.reconcile import RetrainingCompletionService
from app.ml.retraining.service import PolicyDefaults, RetrainingService
from app.models.user import User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_retraining import RetrainingRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_ai_retraining_service import (
    NOW,
    FakeMonitoring,
    FakeQueue,
    _report,
    _specification,
)


@pytest.mark.anyio
async def test_real_retraining_creates_candidate_without_champion_promotion(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    runtime = settings.model_copy(
        update={
            "mlflow_tracking_uri": f"file:{tmp_path / 'mlruns'}",
            "ai_artifact_root": str(tmp_path / "ai-artifacts"),
            "model_artifact_root": str(tmp_path / "model-artifacts"),
        }
    )
    registry = create_ai_model_registry(runtime)
    tracked_training = create_ai_tracked_training_service(
        runtime, model_registry=registry
    )
    user = User(
        email=f"retraining-smoke-{uuid4()}@example.com",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    source_job_id = uuid4()
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        jobs = TrainingJobRepository(session)
        await jobs.create(
            job_id=source_job_id,
            requested_by_user_id=user.id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key="real-source",
            request_fingerprint=_specification().fingerprint(),
            max_attempts=3,
            queued_at=NOW,
        )
        await jobs.commit()

    def assign_candidate(name: str, version: str) -> None:
        registry.assign_alias(name, "candidate", version)

    worker = TrainingJobWorker(
        session_factory=session_factory,
        execute_specification=lambda specification: (
            execute_tracked_training_specification(
                specification,
                service=tracked_training,
                profile_bin_count=10,
            )
        ),
        assign_candidate_alias=assign_candidate,
    )
    assert await worker.execute(source_job_id) is WorkerExecutionState.SUCCEEDED

    async with session_factory() as session:
        source = await TrainingJobRepository(session).get_by_id(source_job_id)
    assert source is not None
    assert source.status is TrainingJobStatus.SUCCEEDED
    assert source.registered_model_version == "1"
    registry.assign_alias("factory_quality", "champion", "1")

    queue = FakeQueue()
    async with session_factory() as session:
        requests = RetrainingRepository(session)
        jobs = TrainingJobRepository(session)
        service = RetrainingService(
            repository=requests,
            monitoring_service=FakeMonitoring(replace(_report(), model_version="1")),
            model_registry=registry,
            training_job_service=TrainingJobService(
                repository=jobs,
                queue=queue,
                max_attempts=3,
            ),
            evaluator=RetrainingPolicyEvaluator(),
            defaults=PolicyDefaults(3600, 1, 3, 1, DriftSeverity.CRITICAL, True),
            clock=lambda: NOW,
        )
        await service.put_policy(
            registered_model_name="factory_quality",
            created_by_user_id=user.id,
            enabled=True,
            allowed_trigger_types=frozenset(RetrainingTriggerType),
            minimum_drift_status=None,
            minimum_current_sample_count=20,
            cooldown_seconds=None,
            maximum_requests_per_day=None,
            maximum_requests_per_week=None,
            maximum_active_requests=None,
            require_champion_source=True,
            allow_truncated_drift=None,
        )
        submitted = await service.evaluate_automatic(
            registered_model_name="factory_quality",
            version_or_alias="champion",
            trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
            start_at=None,
            end_at=None,
            minimum_sample_count=None,
            submit_if_eligible=True,
            requested_by_user_id=user.id,
        )
        assert submitted.request is not None
        retraining_job_id = submitted.request.training_job_id
        assert retraining_job_id is not None

    assert queue.job_ids == [retraining_job_id]
    assert await worker.execute(retraining_job_id) is WorkerExecutionState.SUCCEEDED

    async with session_factory() as session:
        repository = RetrainingRepository(session)
        outcome = await RetrainingCompletionService(repository=repository).synchronize(
            retraining_job_id
        )
        request = await repository.get_request(submitted.request.id)

    assert outcome == "synchronized"
    assert request is not None
    assert request.request_status is RetrainingRequestStatus.COMPLETED
    assert request.resulting_model_version == "2"
    assert request.comparison is not None
    assert registry.resolve("factory_quality", "candidate").version == "2"
    assert registry.resolve("factory_quality", "champion").version == "1"

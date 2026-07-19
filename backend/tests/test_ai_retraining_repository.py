"""Retraining persistence, counters, uniqueness, and audit tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.ml.domain import TaskType
from app.ml.jobs import RandomForestRegressionJobSpec, random_forest_key
from app.ml.monitoring import DriftSeverity
from app.ml.retraining import (
    CooldownState,
    QuotaState,
    RetrainingDecision,
    RetrainingDecisionStatus,
    RetrainingEvaluationMode,
    RetrainingPolicy,
    RetrainingRequest,
    RetrainingRequestStatus,
    RetrainingTrigger,
    RetrainingTriggerType,
)
from app.models.user import User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_retraining import RetrainingRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


def _specification() -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,)),
        training_targets=(0.0, 1.0, 2.0),
        evaluation_features=((0.5,), (1.5,)),
        evaluation_targets=(0.5, 1.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        experiment_name="Retraining Repository",
        registered_model_name="factory_quality",
        tags={"purpose": "source"},
    )


async def _evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    user = User(
        email=f"retraining-{uuid4()}@example.com",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        jobs = TrainingJobRepository(session)
        queued = await jobs.create(
            job_id=uuid4(),
            requested_by_user_id=user.id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key="source-evidence",
            request_fingerprint=_specification().fingerprint(),
            max_attempts=3,
            queued_at=NOW - timedelta(days=2),
        )
        await jobs.commit()
        running = await jobs.claim_queued(job_id=queued.id, started_at=NOW)
        assert running is not None
        await jobs.commit()
        succeeded = await jobs.mark_succeeded(
            job_id=queued.id,
            expected_version=running.state_version,
            finished_at=NOW,
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="experiment-1",
            mlflow_run_id="run-1",
            registered_model_version="3",
            metrics={"rmse": 1.0, "mae": 0.8, "r2": 0.5},
        )
        assert succeeded is not None
        await jobs.commit()
    return user.id, queued.id


def _policy(user_id: UUID) -> RetrainingPolicy:
    return RetrainingPolicy(
        id=uuid4(),
        registered_model_name="factory_quality",
        enabled=True,
        allowed_trigger_types=frozenset(RetrainingTriggerType),
        minimum_drift_status=DriftSeverity.CRITICAL,
        minimum_current_sample_count=20,
        cooldown_seconds=3600,
        maximum_requests_per_day=1,
        maximum_requests_per_week=3,
        maximum_active_requests=1,
        require_champion_source=True,
        allow_truncated_drift=True,
        created_by_user_id=user_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _trigger() -> RetrainingTrigger:
    return RetrainingTrigger(
        RetrainingTriggerType.FEATURE_DRIFT,
        "window:3:start:end",
        DriftSeverity.CRITICAL,
        25,
        25,
        25,
        False,
        None,
        {"psi_critical": 0.25},
    )


def _request(user_id: UUID, source_job_id: UUID, policy_id: UUID) -> RetrainingRequest:
    return RetrainingRequest(
        id=uuid4(),
        registered_model_name="factory_quality",
        source_model_version="3",
        source_training_job_id=source_job_id,
        key=random_forest_key(TaskType.REGRESSION),
        trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
        trigger_reference="window:3:start:end",
        policy_id=policy_id,
        decision_status=RetrainingDecisionStatus.ELIGIBLE,
        request_status=RetrainingRequestStatus.PENDING,
        evaluation_mode=RetrainingEvaluationMode.AUTOMATIC,
        idempotency_key="a" * 64,
        training_job_id=None,
        resulting_model_version=None,
        requested_by_user_id=user_id,
        reason=None,
        override_used=False,
        requested_at=NOW,
        started_at=None,
        completed_at=None,
        safe_failure_code=None,
        safe_failure_message=None,
        comparison=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.anyio
async def test_repository_persists_policy_request_counts_and_blocked_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, source_job_id = await _evidence(session_factory)
    policy = _policy(user_id)
    request = _request(user_id, source_job_id, policy.id)
    decision = RetrainingDecision(
        registered_model_name="factory_quality",
        source_model_version="3",
        requested_alias="champion",
        trigger=_trigger(),
        status=RetrainingDecisionStatus.ELIGIBLE,
        reasons=("Policy eligible.",),
        evaluated_at=NOW,
        cooldown=CooldownState(False, None, None, 0),
        quota=QuotaState(0, 0, 0, 1, 3, 1),
    )

    async with session_factory() as session:
        repository = RetrainingRepository(session)
        saved_policy = await repository.upsert_policy(policy)
        saved_request = await repository.create_request(request)
        audit = await repository.create_audit(
            decision=decision,
            policy_id=policy.id,
            evaluated_by_user_id=user_id,
            mode=RetrainingEvaluationMode.AUTOMATIC,
            override_used=False,
            override_reason=None,
            created_request_id=request.id,
        )
        await repository.commit()

        source = await repository.find_source_training_job(
            registered_model_name="factory_quality", model_version="3"
        )
        duplicate = await repository.get_by_idempotency("a" * 64)
        active = await repository.active_request("factory_quality")
        counts = await repository.request_counts(
            registered_model_name="factory_quality",
            day_start=NOW.replace(hour=0),
            week_start=NOW - timedelta(days=7),
        )
        audits = await repository.list_audits(limit=10, offset=0)

    assert saved_policy.registered_model_name == "factory_quality"
    assert saved_request.source_training_job_id == source_job_id
    assert source is not None and source.registered_model_version == "3"
    assert duplicate is not None and duplicate.id == request.id
    assert active is not None and active.id == request.id
    assert counts[:3] == (1, 1, 1)
    assert counts[3] == NOW
    assert audit.created_request_id == request.id
    assert audits.total == 1
    assert audits.items[0].decision.trigger.thresholds["psi_critical"] == 0.25


@pytest.mark.anyio
async def test_repository_database_uniqueness_prevents_replica_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, source_job_id = await _evidence(session_factory)
    policy = _policy(user_id)
    first = _request(user_id, source_job_id, policy.id)
    repeated = _request(user_id, source_job_id, policy.id)

    async with session_factory() as session:
        repository = RetrainingRepository(session)
        await repository.upsert_policy(policy)
        await repository.create_request(first)
        await repository.commit()
        with pytest.raises(IntegrityError):
            await repository.create_request(repeated)
        await repository.rollback()

        persisted = await repository.get_by_idempotency(first.idempotency_key)

    assert persisted is not None
    assert persisted.id == first.id

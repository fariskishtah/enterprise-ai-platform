"""Bounded retraining reconciliation tests."""

from uuid import uuid4

import pytest
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring import DriftSeverity
from app.ml.retraining import (
    RetrainingPolicyEvaluator,
    RetrainingRequestStatus,
    RetrainingTriggerType,
)
from app.ml.retraining.reconcile import (
    RetrainingCompletionService,
    RetrainingReconciliationService,
)
from app.ml.retraining.service import PolicyDefaults, RetrainingService
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_retraining import RetrainingRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_ai_retraining_service import (
    NOW,
    FakeMonitoring,
    FakeQueue,
    FakeRegistry,
    _report,
    _source_evidence,
    _version,
)


@pytest.mark.anyio
async def test_reconciliation_finalizes_candidate_and_advisory_comparison(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, _ = await _source_evidence(session_factory)
    queue = FakeQueue()
    async with session_factory() as session:
        requests = RetrainingRepository(session)
        jobs = TrainingJobRepository(session)
        service = RetrainingService(
            repository=requests,
            monitoring_service=FakeMonitoring(_report()),
            model_registry=FakeRegistry(_version()),
            training_job_service=TrainingJobService(
                repository=jobs, queue=queue, max_attempts=3
            ),
            evaluator=RetrainingPolicyEvaluator(),
            defaults=PolicyDefaults(3600, 1, 3, 1, DriftSeverity.CRITICAL, True),
            clock=lambda: NOW,
        )
        await service.put_policy(
            registered_model_name="factory_quality",
            created_by_user_id=user_id,
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
        result = await service.evaluate_automatic(
            registered_model_name="factory_quality",
            version_or_alias="champion",
            trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
            start_at=None,
            end_at=None,
            minimum_sample_count=None,
            submit_if_eligible=True,
            requested_by_user_id=user_id,
        )
        assert result.request is not None
        training_job_id = result.request.training_job_id
        assert training_job_id is not None
        running = await jobs.claim_queued(job_id=training_job_id, started_at=NOW)
        assert running is not None
        await jobs.commit()
        completed_job = await jobs.mark_succeeded(
            job_id=training_job_id,
            expected_version=running.state_version,
            finished_at=NOW,
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="experiment",
            mlflow_run_id="candidate-run",
            registered_model_version="4",
            metrics={"rmse": 0.8, "mae": 0.7, "r2": 0.6},
        )
        assert completed_job is not None
        await jobs.commit()

        reconciliation = RetrainingReconciliationService(
            service=service, repository=requests, batch_size=10
        )
        first = await reconciliation.reconcile()
        second = await reconciliation.reconcile()
        repeated_delivery = await RetrainingCompletionService(
            repository=requests
        ).synchronize(training_job_id)
        updated = await requests.get_request(result.request.id)

    assert first.inspected == 1
    assert first.synchronized == 1
    assert second.inspected == 0
    assert repeated_delivery == "no_op"
    assert updated is not None
    assert updated.request_status is RetrainingRequestStatus.COMPLETED
    assert updated.resulting_model_version == "4"
    assert updated.comparison is not None
    assert updated.comparison.status.value == "better"

"""Persisted monitoring evaluation to controlled retraining policy integration."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.ml.domain import TaskType
from app.ml.jobs import random_forest_key
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
)
from app.ml.retraining import (
    RetrainingDecisionStatus,
    RetrainingTriggerType,
)
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_retraining import RetrainingRepository
from app.repositories.monitoring_evaluations import MonitoringEvaluationRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_ai_retraining_service import (
    NOW,
    FakeQueue,
    _service,
    _source_evidence,
)


@pytest.mark.anyio
async def test_persisted_evaluation_creates_only_one_governed_retraining_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, _source_job_id = await _source_evidence(session_factory)
    evaluation = ModelMonitoringEvaluation(
        id=uuid4(),
        registered_model_name="factory_quality",
        model_version="3",
        model_alias="champion",
        key=random_forest_key(TaskType.REGRESSION),
        window_start=NOW - timedelta(hours=24),
        window_end=NOW,
        evaluated_sample_count=25,
        successful_prediction_count=25,
        failed_prediction_count=0,
        data_quality_status=MonitoringEvaluationStatus.HEALTHY,
        feature_drift_status=MonitoringEvaluationStatus.CRITICAL,
        prediction_drift_status=MonitoringEvaluationStatus.HEALTHY,
        operational_health_status=MonitoringEvaluationStatus.HEALTHY,
        overall_status=MonitoringEvaluationStatus.CRITICAL,
        report_schema_version="1.0",
        report={
            "availability": {"error_code": None},
            "drift": {
                "analyzed_event_count": 25,
                "truncated": False,
                "analysis_warning": None,
                "thresholds": {"critical": 0.25, "warning": 0.1},
            },
        },
        warning_count=0,
        critical_count=1,
        trigger=MonitoringEvaluationTrigger.SCHEDULED,
        idempotency_key="persisted-retraining-evaluation",
        created_at=NOW,
        updated_at=NOW,
    )
    queue = FakeQueue()
    async with session_factory() as session:
        await MonitoringEvaluationRepository(session).create(evaluation)
        await session.commit()
        repository = RetrainingRepository(session)
        service = _service(
            repository=repository,
            jobs=TrainingJobService(
                repository=TrainingJobRepository(session),
                queue=queue,
                max_attempts=3,
            ),
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
        first = await service.evaluate_monitoring_evaluation(
            evaluation=evaluation,
            trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
            submit_if_eligible=True,
            requested_by_user_id=user_id,
        )
        repeated = await service.evaluate_monitoring_evaluation(
            evaluation=evaluation,
            trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
            submit_if_eligible=True,
            requested_by_user_id=user_id,
        )
        requests = await repository.list_requests(
            registered_model_name="factory_quality", limit=10, offset=0
        )
        audits = await repository.list_audits(limit=10, offset=0)

    assert first.decision.status is RetrainingDecisionStatus.ELIGIBLE
    assert first.request is not None
    assert first.request.monitoring_evaluation_id == evaluation.id
    assert repeated.decision.status is RetrainingDecisionStatus.BLOCKED_DUPLICATE
    assert repeated.request is not None
    assert repeated.request.id == first.request.id
    assert requests.total == 1
    assert len(queue.job_ids) == 1
    assert audits.total == 2
    assert all(item.monitoring_evaluation_id == evaluation.id for item in audits.items)

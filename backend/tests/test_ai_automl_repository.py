"""AutoML repository optimistic state and durable lease-model tests."""

from uuid import uuid4

import pytest
from app.ml.automl.metrics import MetricDirection
from app.ml.automl.models import AutoMLStudyStatus, AutoMLTrialStatus, SamplerType
from app.ml.domain import TaskType
from app.models.user import User, UserRole
from app.repositories.automl import AutoMLRepository
from app.utils.security import utc_now
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.anyio
async def test_repository_owner_scope_transitions_trials_and_slots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        owner = User(
            email="automl-repository@example.com",
            hashed_password="not-used",
            role=UserRole.ENGINEER,
        )
        session.add(owner)
        await session.flush()
        repository = AutoMLRepository(session)
        now = utc_now()
        study = await repository.create_study(
            requested_by_user_id=owner.id,
            task_type=TaskType.REGRESSION,
            status=AutoMLStudyStatus.QUEUED,
            primary_metric="rmse",
            metric_direction=MetricDirection.MINIMIZE,
            sampler_type=SamplerType.RANDOM,
            random_seed=1,
            plugin_ids=["ridge_regression"],
            search_spaces=[{}],
            preprocessing={},
            data_specification={},
            cross_validation_folds=3,
            trial_budget=2,
            time_budget_seconds=60,
            per_trial_timeout_seconds=10,
            max_concurrent_trials=1,
            register_champion=False,
            request_fingerprint="a" * 64,
            queued_at=now,
        )
        trial = await repository.create_trial(
            study_id=study.id,
            trial_number=0,
            plugin_id="ridge_regression",
            status=AutoMLTrialStatus.QUEUED,
            parameters={"alpha": 1.0},
            parameter_fingerprint="b" * 64,
            random_seed=2,
            queued_at=now,
        )
        transitioned = await repository.conditionally_transition_study(
            study_id=study.id,
            expected_status=AutoMLStudyStatus.QUEUED,
            expected_version=0,
            new_status=AutoMLStudyStatus.RUNNING,
            values={"started_at": now},
        )
        stale = await repository.conditionally_transition_study(
            study_id=study.id,
            expected_status=AutoMLStudyStatus.QUEUED,
            expected_version=0,
            new_status=AutoMLStudyStatus.RUNNING,
        )
        slots = await repository.initialize_slots(2)
        repeated = await repository.initialize_slots(2)
        hidden = await repository.get_owned_study_by_id(study.id, uuid4())
        filtered = await repository.list_studies(
            owner_id=owner.id,
            status=AutoMLStudyStatus.RUNNING,
            task_type=TaskType.REGRESSION,
            plugin_id="ridge_regression",
            requester_id=None,
            limit=10,
            offset=0,
        )
        await repository.commit()

    assert transitioned is not None and transitioned.state_version == 1
    assert stale is None
    assert trial.study_id == study.id
    assert [slot.slot_number for slot in slots] == [1, 2]
    assert len(repeated) == 2
    assert hidden is None
    assert filtered.total == 1

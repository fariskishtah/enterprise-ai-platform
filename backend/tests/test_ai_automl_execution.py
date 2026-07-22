"""Deterministic AutoML materialization, CV, worker, and coordinator tests."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.ml.automl.champion import ChampionCandidate, select_champion
from app.ml.automl.cross_validation import (
    CrossValidationRequest,
    CrossValidationResult,
    execute_cross_validation,
)
from app.ml.automl.execution import ProcessExecutionOutcome, execute_with_timeout
from app.ml.automl.materialization import materialize_trials
from app.ml.automl.metrics import MetricDirection
from app.ml.automl.models import AutoMLStudyStatus, SamplerType
from app.ml.domain import TaskType
from app.ml.plugins import create_default_plugin_registry
from app.models.user import User, UserRole
from app.repositories.automl import AutoMLRepository
from app.services.automl_execution import (
    AutoMLCoordinator,
    AutoMLExecutionState,
    AutoMLReconciler,
    AutoMLTrialWorker,
)
from app.utils.security import utc_now
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class MemoryAutoMLQueue:
    def __init__(self) -> None:
        self.studies: list[UUID] = []
        self.trials: list[UUID] = []

    def enqueue_study(self, study_id: UUID) -> str:
        self.studies.append(study_id)
        return f"study-{len(self.studies)}"

    def enqueue_trial(self, trial_id: UUID) -> str:
        self.trials.append(trial_id)
        return f"trial-{len(self.trials)}"


def regression_request() -> CrossValidationRequest:
    return CrossValidationRequest(
        task_type=TaskType.REGRESSION,
        plugin_id="ridge_regression",
        parameters={"alpha": 1.0, "fit_intercept": True},
        scaler="standard",
        imputer="none",
        primary_metric="rmse",
        metric_direction=MetricDirection.MINIMIZE,
        random_seed=17,
        folds=3,
        features=((0.0,), (1.0,), (2.0,), (3.0,), (4.0,), (5.0,)),
        targets=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
    )


def test_materialization_is_deterministic_fair_and_bounded() -> None:
    registry = create_default_plugin_registry()
    plugin_ids = ("ridge_regression", "decision_tree_regression")
    spaces = tuple(registry.get(plugin).automl_search_space for plugin in plugin_ids)
    assert all(space is not None for space in spaces)
    validated_spaces = tuple(space for space in spaces if space is not None)
    first = materialize_trials(
        task_type=TaskType.REGRESSION,
        plugin_ids=plugin_ids,
        search_spaces=validated_spaces,
        study_seed=31,
        trial_budget=6,
    )
    second = materialize_trials(
        task_type=TaskType.REGRESSION,
        plugin_ids=plugin_ids,
        search_spaces=validated_spaces,
        study_seed=31,
        trial_budget=6,
    )
    assert first == second
    assert [trial.plugin_id for trial in first.trials] == [
        plugin_ids[number % 2] for number in range(6)
    ]
    assert len({trial.parameter_fingerprint for trial in first.trials}) == 6


def test_regression_and_classification_cv_are_deterministic_and_finite() -> None:
    first = execute_cross_validation(regression_request())
    second = execute_cross_validation(regression_request())
    assert first == second
    assert len(first.fold_metrics) == 3
    assert first.primary_metric_value == first.aggregate_metrics["rmse_mean"]
    classification = execute_cross_validation(
        CrossValidationRequest(
            task_type=TaskType.CLASSIFICATION,
            plugin_id="logistic_regression",
            parameters={"C": 1.0, "class_weight": "none"},
            scaler="standard",
            imputer="none",
            primary_metric="accuracy",
            metric_direction=MetricDirection.MAXIMIZE,
            random_seed=11,
            folds=2,
            features=((0.0,), (0.2,), (0.4,), (2.0,), (2.2,), (2.4,)),
            targets=(0, 0, 0, 1, 1, 1),
        )
    )
    assert len(classification.fold_metrics) == 2
    with pytest.raises(ValueError, match="minimum class count"):
        execute_cross_validation(
            CrossValidationRequest(
                task_type=TaskType.CLASSIFICATION,
                plugin_id="logistic_regression",
                parameters={"C": 1.0, "class_weight": "none"},
                scaler="standard",
                imputer="none",
                primary_metric="accuracy",
                metric_direction=MetricDirection.MAXIMIZE,
                random_seed=11,
                folds=3,
                features=((0.0,), (0.2,), (2.0,), (2.2,)),
                targets=(0, 0, 1, 1),
            )
        )


def test_spawn_process_returns_typed_result_and_enforces_timeout() -> None:
    successful = execute_with_timeout(regression_request(), timeout_seconds=10)
    assert successful.succeeded
    timed_out = execute_with_timeout(regression_request(), timeout_seconds=0.0001)
    assert timed_out.error_code == "trial_timeout"


def test_champion_ranking_uses_direction_variance_and_trial_number() -> None:
    candidates = (
        ChampionCandidate(uuid4(), 2, 0.9, 0.2),
        ChampionCandidate(uuid4(), 1, 0.9, 0.1),
        ChampionCandidate(uuid4(), 0, 0.8, 0.0),
    )
    assert select_champion(candidates, MetricDirection.MAXIMIZE) == candidates[1]
    assert select_champion(candidates, MetricDirection.MINIMIZE) == candidates[2]


@pytest.mark.anyio
async def test_coordinator_worker_slots_and_reconciliation_are_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queue = MemoryAutoMLQueue()
    study_id = await _create_executable_study(session_factory)
    async with session_factory() as session:
        coordinator = AutoMLCoordinator(
            repository=AutoMLRepository(session), queue=queue, global_slots=1
        )
        assert await coordinator.coordinate(study_id) is AutoMLExecutionState.PROGRESSED
        repeated = await coordinator.coordinate(study_id)
        assert repeated is AutoMLExecutionState.SKIPPED
    assert len(queue.trials) == 1

    def successful_process(
        _: CrossValidationRequest, **__: object
    ) -> ProcessExecutionOutcome:
        return ProcessExecutionOutcome(
            CrossValidationResult(
                fold_metrics=({"rmse": 0.5}, {"rmse": 0.7}),
                aggregate_metrics={"rmse_mean": 0.6, "rmse_std": 0.1},
                primary_metric_value=0.6,
            ),
            None,
            None,
        )

    worker = AutoMLTrialWorker(
        session_factory=session_factory,
        queue=queue,
        lease_seconds=60,
        process_executor=successful_process,
    )
    assert await worker.execute(queue.trials[0]) is AutoMLExecutionState.TERMINAL
    assert await worker.execute(queue.trials[0]) is AutoMLExecutionState.SKIPPED

    async with session_factory() as session:
        coordinator = AutoMLCoordinator(
            repository=AutoMLRepository(session), queue=queue, global_slots=1
        )
        assert await coordinator.coordinate(study_id) is AutoMLExecutionState.PROGRESSED
    assert len(queue.trials) == 2
    assert await worker.execute(queue.trials[1]) is AutoMLExecutionState.TERMINAL
    async with session_factory() as session:
        coordinator = AutoMLCoordinator(
            repository=AutoMLRepository(session), queue=queue, global_slots=1
        )
        assert await coordinator.coordinate(study_id) is AutoMLExecutionState.TERMINAL
        study = await AutoMLRepository(session).get_study_by_id(study_id)
        assert study is not None
        assert study.status is AutoMLStudyStatus.SUCCEEDED
        assert study.best_trial_id is not None
        slots, trials = await AutoMLReconciler(
            AutoMLRepository(session), queue
        ).reconcile()
        assert (slots, trials) == (0, 0)


async def _create_executable_study(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    registry = create_default_plugin_registry()
    space = registry.get("ridge_regression").automl_search_space
    assert space is not None
    async with session_factory() as session:
        owner = User(
            email=f"automl-execution-{uuid4()}@example.com",
            hashed_password="unused",
            role=UserRole.ENGINEER,
        )
        session.add(owner)
        await session.flush()
        study = await AutoMLRepository(session).create_study(
            requested_by_user_id=owner.id,
            task_type=TaskType.REGRESSION,
            status=AutoMLStudyStatus.QUEUED,
            primary_metric="rmse",
            metric_direction=MetricDirection.MINIMIZE,
            sampler_type=SamplerType.RANDOM,
            random_seed=17,
            plugin_ids=["ridge_regression"],
            search_spaces=[space.model_dump(mode="json")],
            preprocessing={"scaler": "standard", "imputer": "none"},
            data_specification={
                "training_data_fingerprint": "a" * 64,
                "evaluation_data_fingerprint": "b" * 64,
                "training_row_count": 6,
                "evaluation_row_count": 2,
                "feature_count": 1,
                "training_features": [[0.0], [1.0], [2.0], [3.0], [4.0], [5.0]],
                "training_targets": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                "evaluation_features": [[0.5], [4.5]],
                "evaluation_targets": [0.5, 4.5],
            },
            cross_validation_folds=3,
            trial_budget=2,
            time_budget_seconds=120,
            per_trial_timeout_seconds=30,
            max_concurrent_trials=1,
            register_champion=False,
            request_fingerprint="c" * 64,
            queued_at=utc_now(),
            deadline_at=utc_now() + timedelta(seconds=120),
        )
        await session.commit()
        return study.id

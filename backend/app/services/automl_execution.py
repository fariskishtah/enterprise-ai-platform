"""Durable AutoML coordinator, trial worker, and reconciliation services."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from threading import Event
from time import perf_counter
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ml.automl.champion import ChampionCandidate, select_champion
from app.ml.automl.cross_validation import CrossValidationRequest
from app.ml.automl.execution import ProcessExecutionOutcome, execute_with_timeout
from app.ml.automl.materialization import materialize_trials
from app.ml.automl.models import (
    AutoMLDataSpecificationReference,
    AutoMLStudyStatus,
    AutoMLTrialStatus,
)
from app.ml.automl.queue import AutoMLQueue
from app.ml.automl.search_space import PluginAutoMLSearchSpace
from app.ml.domain import TaskType
from app.ml.jobs.models import (
    PluginClassificationJobSpec,
    PluginRegressionJobSpec,
    PreprocessingJobConfig,
    TrainingJobStatus,
)
from app.ml.jobs.service import TrainingJobService
from app.ml.plugins import create_default_plugin_registry
from app.models.automl import AutoMLStudy, AutoMLTrial
from app.observability.logging import emit_safe
from app.observability.metrics import record_automl_event, record_automl_slot_delta
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.automl import AutoMLRepository
from app.utils.security import as_utc, utc_now

logger = logging.getLogger(__name__)
type ProcessExecutor = Callable[..., ProcessExecutionOutcome]


class AutoMLExecutionState(StrEnum):
    PROGRESSED = "progressed"
    RETRY = "retry"
    TERMINAL = "terminal"
    SKIPPED = "skipped"


class AutoMLCoordinator:
    """Materialize, schedule, and finalize one study without busy looping."""

    def __init__(
        self,
        *,
        repository: AutoMLRepository,
        queue: AutoMLQueue,
        global_slots: int = 1,
        training_service: TrainingJobService | None = None,
        training_repository: TrainingJobRepository | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._global_slots = global_slots
        self._training_service = training_service
        self._training_repository = training_repository

    async def coordinate(self, study_id: UUID) -> AutoMLExecutionState:
        study = await self._repository.get_study_by_id(study_id)
        if study is None or study.status in {
            AutoMLStudyStatus.SUCCEEDED,
            AutoMLStudyStatus.FAILED,
            AutoMLStudyStatus.CANCELLED,
        }:
            return AutoMLExecutionState.SKIPPED
        now = utc_now()
        if study.status is AutoMLStudyStatus.QUEUED:
            started = await self._repository.conditionally_transition_study(
                study_id=study.id,
                expected_status=AutoMLStudyStatus.QUEUED,
                expected_version=study.state_version,
                new_status=AutoMLStudyStatus.RUNNING,
                values={
                    "started_at": now,
                    "deadline_at": now + timedelta(seconds=study.time_budget_seconds),
                    "queue_message_id": None,
                },
            )
            if started is None:
                await self._repository.rollback()
                return AutoMLExecutionState.SKIPPED
            study = started
            await self._repository.commit()
        await self._repository.initialize_slots(self._global_slots)
        await self._repository.commit()
        study = await self._repository.get_study_by_id(study_id)
        if study is None:
            return AutoMLExecutionState.SKIPPED
        if study.cancel_requested_at is not None:
            await self._repository.mark_queued_trials_cancelled(study.id, now)
            await self._repository.commit()
            return await self._finalize_cancellation(study)
        if study.deadline_at is not None and as_utc(study.deadline_at) <= now:
            await self._repository.mark_queued_trials_cancelled(study.id, now)
            await self._repository.commit()
        trials = await self._repository.list_all_trials(study.id)
        if not trials and (
            study.deadline_at is None or as_utc(study.deadline_at) > now
        ):
            try:
                materialized = materialize_trials(
                    task_type=study.task_type,
                    plugin_ids=tuple(study.plugin_ids),
                    search_spaces=tuple(
                        PluginAutoMLSearchSpace.model_validate(item)
                        for item in study.search_spaces
                    ),
                    study_seed=study.random_seed,
                    trial_budget=study.trial_budget,
                )
                for trial_spec in materialized.trials:
                    await self._repository.create_trial(
                        study_id=study.id,
                        trial_number=trial_spec.trial_number,
                        plugin_id=trial_spec.plugin_id,
                        status=AutoMLTrialStatus.QUEUED,
                        parameters=trial_spec.sampled_parameters,
                        parameter_fingerprint=trial_spec.parameter_fingerprint,
                        random_seed=trial_spec.trial_seed,
                        max_attempts=3,
                        queued_at=now,
                    )
                if materialized.exhausted:
                    await self._repository.update_study_error(
                        study_id=study.id,
                        expected_version=study.state_version,
                        error_code="search_space_exhausted",
                        safe_error_message=(
                            "The finite search space was exhausted before the "
                            "trial budget."
                        ),
                    )
                await self._repository.commit()
            except (ValueError, ValidationError):
                await self._repository.rollback()
                await self._fail_study(
                    study,
                    "materialization_failed",
                    "The persisted AutoML search space could not be materialized.",
                )
                return AutoMLExecutionState.TERMINAL
            trials = await self._repository.list_all_trials(study.id)
        running = [
            trial for trial in trials if trial.status is AutoMLTrialStatus.RUNNING
        ]
        dispatched = [
            trial
            for trial in trials
            if trial.status is AutoMLTrialStatus.QUEUED
            and trial.queue_message_id is not None
        ]
        queued = [
            trial
            for trial in trials
            if trial.status is AutoMLTrialStatus.QUEUED
            and trial.queue_message_id is None
        ]
        capacity = max(study.max_concurrent_trials - len(running) - len(dispatched), 0)
        scheduled = 0
        for trial in queued[:capacity]:
            try:
                message_id = self._queue.enqueue_trial(trial.id)
            except Exception:
                emit_safe(
                    logger,
                    logging.ERROR,
                    "automl_trial_enqueue_failed",
                    extra={"lifecycle_status": "recoverable"},
                    exc_info=True,
                )
                continue
            updated = await self._repository.set_trial_queue_identifier(
                trial_id=trial.id,
                queue_message_id=message_id,
                expected_version=trial.state_version,
            )
            if updated is not None:
                scheduled += 1
                await self._repository.commit()
            else:
                await self._repository.rollback()
        if scheduled:
            return AutoMLExecutionState.PROGRESSED
        trials = await self._repository.list_all_trials(study.id)
        if any(
            trial.status in {AutoMLTrialStatus.QUEUED, AutoMLTrialStatus.RUNNING}
            for trial in trials
        ):
            return AutoMLExecutionState.SKIPPED
        return await self._finalize(study, trials)

    async def _finalize_cancellation(self, study: AutoMLStudy) -> AutoMLExecutionState:
        trials = await self._repository.list_all_trials(study.id)
        if any(trial.status is AutoMLTrialStatus.RUNNING for trial in trials):
            return AutoMLExecutionState.SKIPPED
        current = await self._repository.get_study_by_id(study.id)
        if current is None or current.status is not AutoMLStudyStatus.RUNNING:
            return AutoMLExecutionState.SKIPPED
        now = utc_now()
        changed = await self._repository.conditionally_transition_study(
            study_id=current.id,
            expected_status=AutoMLStudyStatus.RUNNING,
            expected_version=current.state_version,
            new_status=AutoMLStudyStatus.CANCELLED,
            values={"cancelled_at": now, "finished_at": now},
        )
        if changed is None:
            await self._repository.rollback()
            return AutoMLExecutionState.SKIPPED
        await self._repository.commit()
        record_automl_event(event="study_terminal", final_status="cancelled")
        return AutoMLExecutionState.TERMINAL

    async def _finalize(
        self, study: AutoMLStudy, trials: tuple[AutoMLTrial, ...]
    ) -> AutoMLExecutionState:
        candidates = tuple(
            ChampionCandidate(
                trial.id,
                trial.trial_number,
                trial.primary_metric_value,
                float(
                    (trial.aggregate_metrics or {}).get(
                        f"{study.primary_metric}_std", 1e308
                    )
                ),
            )
            for trial in trials
            if trial.status is AutoMLTrialStatus.SUCCEEDED
            and trial.primary_metric_value is not None
        )
        champion = select_champion(candidates, study.metric_direction)
        if champion is None:
            await self._fail_study(
                study,
                "no_successful_trials",
                "No AutoML trial completed successfully.",
            )
            return AutoMLExecutionState.TERMINAL
        current = await self._repository.get_study_by_id(study.id)
        if current is None:
            return AutoMLExecutionState.SKIPPED
        if current.best_trial_id is None:
            linked = await self._repository.set_best_trial(
                study_id=current.id,
                trial_id=champion.trial_id,
                expected_version=current.state_version,
            )
            if linked is None:
                await self._repository.rollback()
                return AutoMLExecutionState.SKIPPED
            await self._repository.commit()
            current = linked
        if current.register_champion:
            return await self._handoff(current, trials)
        finished = await self._repository.conditionally_transition_study(
            study_id=current.id,
            expected_status=AutoMLStudyStatus.RUNNING,
            expected_version=current.state_version,
            new_status=AutoMLStudyStatus.SUCCEEDED,
            values={
                "finished_at": utc_now(),
                "error_code": None,
                "safe_error_message": None,
            },
        )
        if finished is None:
            await self._repository.rollback()
            return AutoMLExecutionState.SKIPPED
        await self._repository.append_terminal_audit(finished)
        await self._repository.commit()
        record_automl_event(event="study_terminal", final_status="succeeded")
        return AutoMLExecutionState.TERMINAL

    async def _handoff(
        self, study: AutoMLStudy, trials: tuple[AutoMLTrial, ...]
    ) -> AutoMLExecutionState:
        if self._training_service is None:
            return AutoMLExecutionState.RETRY
        if study.champion_training_job_id is not None:
            if self._training_repository is None:
                return AutoMLExecutionState.RETRY
            job = await self._training_repository.get_by_id(
                study.champion_training_job_id
            )
            if job is None or job.status in {
                TrainingJobStatus.QUEUED,
                TrainingJobStatus.RUNNING,
            }:
                return AutoMLExecutionState.SKIPPED
            final = (
                AutoMLStudyStatus.SUCCEEDED
                if job.status is TrainingJobStatus.SUCCEEDED
                else AutoMLStudyStatus.FAILED
            )
            changed = await self._repository.conditionally_transition_study(
                study_id=study.id,
                expected_status=AutoMLStudyStatus.RUNNING,
                expected_version=study.state_version,
                new_status=final,
                values={
                    "finished_at": utc_now(),
                    "error_code": (
                        None
                        if final is AutoMLStudyStatus.SUCCEEDED
                        else "champion_training_failed"
                    ),
                    "safe_error_message": (
                        None
                        if final is AutoMLStudyStatus.SUCCEEDED
                        else "The champion training job failed."
                    ),
                },
            )
            if changed is not None:
                await self._repository.append_terminal_audit(changed)
                await self._repository.commit()
                record_automl_event(event="study_terminal", final_status=final.value)
                return AutoMLExecutionState.TERMINAL
            await self._repository.rollback()
            return AutoMLExecutionState.SKIPPED
        trial = next(item for item in trials if item.id == study.best_trial_id)
        specification = _training_specification(study, trial)
        plugin = create_default_plugin_registry().get(trial.plugin_id, study.task_type)
        submission = await self._training_service.submit(
            requested_by_user_id=study.requested_by_user_id,
            key=plugin.key,
            specification=specification,
            idempotency_key=f"automl-study-{study.id}",
        )
        current = await self._repository.get_study_by_id(study.id)
        if current is None:
            return AutoMLExecutionState.SKIPPED
        linked = await self._repository.link_champion_training_job(
            study_id=current.id,
            training_job_id=submission.job.id,
            expected_version=current.state_version,
        )
        if linked is None:
            await self._repository.rollback()
            return AutoMLExecutionState.SKIPPED
        await self._repository.commit()
        record_automl_event(event="champion_handoff", final_status="submitted")
        return AutoMLExecutionState.PROGRESSED

    async def _fail_study(self, study: AutoMLStudy, code: str, message: str) -> None:
        current = await self._repository.get_study_by_id(study.id)
        if current is None or current.status is not AutoMLStudyStatus.RUNNING:
            return
        changed = await self._repository.conditionally_transition_study(
            study_id=current.id,
            expected_status=AutoMLStudyStatus.RUNNING,
            expected_version=current.state_version,
            new_status=AutoMLStudyStatus.FAILED,
            values={
                "finished_at": utc_now(),
                "error_code": code,
                "safe_error_message": message,
            },
        )
        if changed is not None:
            await self._repository.append_terminal_audit(changed)
            await self._repository.commit()
            record_automl_event(event="study_terminal", final_status="failed")
        else:
            await self._repository.rollback()


class AutoMLTrialWorker:
    """Claim one durable slot, execute isolated CV, and persist once."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        queue: AutoMLQueue,
        lease_seconds: int,
        process_executor: ProcessExecutor = execute_with_timeout,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._lease_seconds = lease_seconds
        self._process_executor = process_executor

    async def execute(self, trial_id: UUID) -> AutoMLExecutionState:
        now = utc_now()
        async with self._session_factory() as session:
            repository = AutoMLRepository(session)
            claimed = await repository.claim_trial_and_slot(
                trial_id=trial_id,
                now=now,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
            )
            if claimed is None:
                await repository.rollback()
                return AutoMLExecutionState.SKIPPED
            trial, slot = claimed
            study = await repository.get_study_by_id(trial.study_id)
            if study is None:
                await repository.rollback()
                return AutoMLExecutionState.SKIPPED
            try:
                request = _cv_request(study, trial)
            except (ValueError, ValidationError):
                failed = await repository.conditionally_transition_trial(
                    trial_id=trial.id,
                    expected_status=AutoMLTrialStatus.RUNNING,
                    expected_version=trial.state_version,
                    new_status=AutoMLTrialStatus.FAILED,
                    values={
                        "finished_at": utc_now(),
                        "lease_expires_at": None,
                        "error_code": "trial_validation_failed",
                        "safe_error_message": (
                            "The persisted AutoML trial could not be validated."
                        ),
                    },
                )
                released = await repository.release_slot(
                    slot_number=slot.slot_number,
                    trial_id=trial.id,
                    expected_version=slot.state_version,
                )
                if failed is not None and released:
                    await repository.commit()
                    record_automl_event(event="trial_terminal", final_status="failed")
                    try:
                        self._queue.enqueue_study(study.id)
                    except Exception:
                        return AutoMLExecutionState.RETRY
                    return AutoMLExecutionState.TERMINAL
                await repository.rollback()
                return AutoMLExecutionState.SKIPPED
            await repository.commit()
            record_automl_slot_delta(1)
            trial_version = trial.state_version
            slot_version = slot.state_version
            slot_number = slot.slot_number
        cancelled = Event()
        execution_started = perf_counter()
        execution = asyncio.create_task(
            asyncio.to_thread(
                self._process_executor,
                request,
                timeout_seconds=min(
                    study.per_trial_timeout_seconds,
                    (
                        max((as_utc(study.deadline_at) - now).total_seconds(), 0.01)
                        if study.deadline_at is not None
                        else study.per_trial_timeout_seconds
                    ),
                ),
                cancelled=cancelled.is_set,
            )
        )
        while not execution.done():
            await asyncio.sleep(0.05)
            async with self._session_factory() as session:
                polled_study = await AutoMLRepository(session).get_study_by_id(study.id)
            if polled_study is None or polled_study.cancel_requested_at is not None:
                cancelled.set()
        outcome = await execution
        async with self._session_factory() as session:
            repository = AutoMLRepository(session)
            current_trial = await repository.get_trial_by_id(trial.id)
            current_study = await repository.get_study_by_id(study.id)
            if current_trial is None or current_trial.state_version != trial_version:
                await repository.rollback()
                return AutoMLExecutionState.SKIPPED
            final_status = AutoMLTrialStatus.SUCCEEDED
            values: dict[str, object] = {
                "finished_at": utc_now(),
                "lease_expires_at": None,
            }
            if (
                current_study is None
                or current_study.cancel_requested_at is not None
                or outcome.error_code == "cancelled"
            ):
                final_status = AutoMLTrialStatus.CANCELLED
                values["cancelled_at"] = utc_now()
            elif outcome.result is not None:
                metrics = await repository.update_trial_metrics(
                    trial_id=current_trial.id,
                    expected_version=current_trial.state_version,
                    fold_metrics=[dict(item) for item in outcome.result.fold_metrics],
                    aggregate_metrics=dict(outcome.result.aggregate_metrics),
                    primary_metric_value=outcome.result.primary_metric_value,
                    duration_seconds=max(perf_counter() - execution_started, 0.0),
                )
                if metrics is None:
                    await repository.rollback()
                    return AutoMLExecutionState.SKIPPED
                current_trial = metrics
            elif (
                outcome.error_code == "process_start_failed"
                and current_trial.attempt_count < current_trial.max_attempts
            ):
                retry = await repository.conditionally_transition_trial(
                    trial_id=current_trial.id,
                    expected_status=AutoMLTrialStatus.RUNNING,
                    expected_version=current_trial.state_version,
                    new_status=AutoMLTrialStatus.QUEUED,
                    values={
                        "queue_message_id": None,
                        "lease_expires_at": None,
                        "error_code": outcome.error_code,
                        "safe_error_message": outcome.safe_error_message,
                    },
                )
                released = await repository.release_slot(
                    slot_number=slot_number,
                    trial_id=current_trial.id,
                    expected_version=slot_version,
                )
                if retry is None or not released:
                    await repository.rollback()
                    return AutoMLExecutionState.SKIPPED
                await repository.commit()
                record_automl_slot_delta(-1)
                record_automl_event(event="trial_retry", final_status="queued")
                try:
                    self._queue.enqueue_study(study.id)
                except Exception:
                    return AutoMLExecutionState.RETRY
                return AutoMLExecutionState.RETRY
            else:
                final_status = AutoMLTrialStatus.FAILED
                values.update(
                    error_code=outcome.error_code,
                    safe_error_message=outcome.safe_error_message,
                )
            terminal = await repository.conditionally_transition_trial(
                trial_id=current_trial.id,
                expected_status=AutoMLTrialStatus.RUNNING,
                expected_version=current_trial.state_version,
                new_status=final_status,
                values=values,
            )
            released = await repository.release_slot(
                slot_number=slot_number,
                trial_id=current_trial.id,
                expected_version=slot_version,
            )
            if terminal is None or not released:
                await repository.rollback()
                return AutoMLExecutionState.SKIPPED
            await repository.commit()
            record_automl_slot_delta(-1)
            record_automl_event(
                event="trial_terminal",
                final_status=final_status.value,
                duration_seconds=max(perf_counter() - execution_started, 0.0),
            )
        try:
            self._queue.enqueue_study(study.id)
        except Exception:
            return AutoMLExecutionState.RETRY
        return AutoMLExecutionState.TERMINAL


class AutoMLReconciler:
    def __init__(self, repository: AutoMLRepository, queue: AutoMLQueue) -> None:
        self._repository = repository
        self._queue = queue

    async def reconcile(self) -> tuple[int, int]:
        now = utc_now()
        slots = await self._repository.reclaim_expired_slots(now)
        trials = await self._repository.release_expired_trials(now)
        await self._repository.fail_exhausted_expired_trials(now)
        page = await self._repository.list_studies(
            owner_id=None,
            status=None,
            task_type=None,
            plugin_id=None,
            requester_id=None,
            limit=100,
            offset=0,
        )
        await self._repository.commit()
        if slots or trials:
            record_automl_event(event="reconciliation_repair", final_status="repaired")
        if slots:
            record_automl_slot_delta(-slots)
        for study in page.items:
            if study.status in {AutoMLStudyStatus.QUEUED, AutoMLStudyStatus.RUNNING}:
                try:
                    message_id = self._queue.enqueue_study(study.id)
                except Exception:
                    continue
                updated = await self._repository.set_study_queue_identifier(
                    study_id=study.id,
                    queue_message_id=message_id,
                    expected_version=study.state_version,
                )
                if updated is not None:
                    await self._repository.commit()
                else:
                    await self._repository.rollback()
        return slots, trials


def _cv_request(study: AutoMLStudy, trial: AutoMLTrial) -> CrossValidationRequest:
    data = AutoMLDataSpecificationReference.model_validate(study.data_specification)
    if (
        not data.executable
        or data.training_features is None
        or data.training_targets is None
    ):
        raise ValueError("The AutoML study has no executable data snapshot.")
    preprocessing = PreprocessingJobConfig.model_validate(study.preprocessing)
    if study.task_type is TaskType.CLASSIFICATION and any(
        type(value) is not int for value in data.training_targets
    ):
        raise ValueError("Classification AutoML targets must be integer labels.")
    return CrossValidationRequest(
        task_type=study.task_type,
        plugin_id=trial.plugin_id,
        parameters=trial.parameters,
        scaler=preprocessing.scaler,
        imputer=preprocessing.imputer,
        primary_metric=study.primary_metric,
        metric_direction=study.metric_direction,
        random_seed=trial.random_seed,
        folds=study.cross_validation_folds,
        features=data.training_features,
        targets=data.training_targets,
    )


def _training_specification(
    study: AutoMLStudy, trial: AutoMLTrial
) -> PluginRegressionJobSpec | PluginClassificationJobSpec:
    data = AutoMLDataSpecificationReference.model_validate(study.data_specification)
    if (
        data.training_features is None
        or data.training_targets is None
        or data.evaluation_features is None
        or data.evaluation_targets is None
        or study.registered_model_name is None
    ):
        raise ValueError("Champion training requires a complete execution snapshot.")
    common: dict[str, object] = {
        "plugin_id": trial.plugin_id,
        "training_features": data.training_features,
        "evaluation_features": data.evaluation_features,
        "dataset_version_id": data.dataset_version_id,
        "dataset_schema_snapshot": data.dataset_schema_snapshot,
        "hyperparameters": trial.parameters,
        "preprocessing": study.preprocessing,
        "random_seed": trial.random_seed,
        "experiment_name": f"AutoML {study.id}",
        "run_name": f"automl-champion-{trial.trial_number}",
        "registered_model_name": study.registered_model_name,
        "tags": {"workflow": "automl"},
    }
    if study.task_type is TaskType.CLASSIFICATION:
        return PluginClassificationJobSpec(
            **common,
            training_targets=tuple(int(value) for value in data.training_targets),
            evaluation_targets=tuple(int(value) for value in data.evaluation_targets),
        )
    return PluginRegressionJobSpec(
        **common,
        training_targets=tuple(float(value) for value in data.training_targets),
        evaluation_targets=tuple(float(value) for value in data.evaluation_targets),
    )

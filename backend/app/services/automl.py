"""Management-only AutoML study application service."""

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.ml.automl.models import (
    AutoMLStudySpecification,
    AutoMLStudyStatus,
    AutoMLTrialStatus,
)
from app.ml.domain import TaskType
from app.models.automl import AutoMLStudy, AutoMLTrial
from app.observability.logging import emit_safe
from app.observability.metrics import record_automl_event
from app.repositories.automl import AutoMLRepository, AutoMLStudyPage, AutoMLTrialPage
from app.utils.security import utc_now

logger = logging.getLogger("app.security.audit")


class AutoMLNotFoundError(RuntimeError):
    pass


class AutoMLConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AutoMLSubmission:
    study: AutoMLStudy
    created: bool


class AutoMLService:
    """Validate and persist studies without starting execution."""

    def __init__(self, repository: AutoMLRepository) -> None:
        self._repository = repository

    async def create_study(
        self,
        *,
        owner_id: UUID,
        specification: AutoMLStudySpecification,
        idempotency_key: str | None,
    ) -> AutoMLSubmission:
        key = idempotency_key.strip() if idempotency_key else None
        fingerprint = specification.fingerprint()
        if key:
            existing = await self._repository.find_by_scoped_idempotency_key(
                owner_id, key
            )
            if existing is not None:
                return self._replay(existing, fingerprint)
        now = utc_now()
        budget = specification.budget
        try:
            study = await self._repository.create_study(
                id=uuid4(),
                requested_by_user_id=owner_id,
                task_type=specification.task_type,
                status=AutoMLStudyStatus.QUEUED,
                primary_metric=specification.primary_metric,
                metric_direction=specification.metric_direction,
                sampler_type=specification.sampler_type,
                random_seed=specification.random_seed,
                plugin_ids=list(specification.plugin_ids),
                search_spaces=[
                    space.model_dump(mode="json")
                    for space in specification.plugin_search_spaces
                ],
                preprocessing=specification.preprocessing.model_dump(mode="json"),
                data_specification=specification.data.model_dump(mode="json"),
                cross_validation_folds=budget.cross_validation_folds,
                trial_budget=budget.trial_budget,
                time_budget_seconds=budget.time_budget_seconds,
                per_trial_timeout_seconds=budget.per_trial_timeout_seconds,
                max_concurrent_trials=budget.max_concurrent_trials,
                register_champion=specification.register_champion,
                registered_model_name=specification.registered_model_name,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                queued_at=now,
            )
            await self._repository.commit()
        except IntegrityError:
            await self._repository.rollback()
            if not key:
                raise
            existing = await self._repository.find_by_scoped_idempotency_key(
                owner_id, key
            )
            if existing is None:
                raise
            return self._replay(existing, fingerprint)
        emit_safe(
            logger,
            logging.INFO,
            "automl_study_created",
            extra={
                "audit_event": "automl_study_created",
                "outcome": "accepted",
                "task_type": specification.task_type.value,
            },
        )
        record_automl_event(event="study_created", final_status="queued")
        return AutoMLSubmission(study, True)

    def _replay(self, study: AutoMLStudy, fingerprint: str) -> AutoMLSubmission:
        if study.request_fingerprint != fingerprint:
            emit_safe(
                logger,
                logging.WARNING,
                "automl_idempotency_conflict",
                extra={
                    "audit_event": "automl_idempotency_conflict",
                    "outcome": "denied",
                },
            )
            raise AutoMLConflictError(
                "The idempotency key was already used with a different request."
            )
        emit_safe(
            logger,
            logging.INFO,
            "automl_idempotent_replay",
            extra={"audit_event": "automl_idempotent_replay", "outcome": "accepted"},
        )
        return AutoMLSubmission(study, False)

    async def get_study(
        self, *, study_id: UUID, user_id: UUID, is_admin: bool
    ) -> AutoMLStudy:
        study = await (
            self._repository.get_study_by_id(study_id)
            if is_admin
            else self._repository.get_owned_study_by_id(study_id, user_id)
        )
        if study is None:
            raise AutoMLNotFoundError("AutoML study not found.")
        return study

    async def list_studies(
        self,
        *,
        user_id: UUID,
        is_admin: bool,
        status: AutoMLStudyStatus | None,
        task_type: TaskType | None,
        plugin_id: str | None,
        requester_id: UUID | None,
        limit: int,
        offset: int,
    ) -> AutoMLStudyPage:
        return await self._repository.list_studies(
            owner_id=None if is_admin else user_id,
            requester_id=requester_id if is_admin else None,
            status=status,
            task_type=task_type,
            plugin_id=plugin_id,
            limit=limit,
            offset=offset,
        )

    async def list_trials(
        self,
        *,
        study_id: UUID,
        user_id: UUID,
        is_admin: bool,
        status: AutoMLTrialStatus | None,
        plugin_id: str | None,
        limit: int,
        offset: int,
        metric_descending: bool,
    ) -> AutoMLTrialPage:
        await self.get_study(study_id=study_id, user_id=user_id, is_admin=is_admin)
        return await self._repository.list_trials_for_study(
            study_id=study_id,
            status=status,
            plugin_id=plugin_id,
            limit=limit,
            offset=offset,
            metric_descending=metric_descending,
        )

    async def get_trial(
        self, *, study_id: UUID, trial_id: UUID, user_id: UUID, is_admin: bool
    ) -> AutoMLTrial:
        await self.get_study(study_id=study_id, user_id=user_id, is_admin=is_admin)
        trial = await self._repository.get_trial_by_id(trial_id)
        if trial is None or trial.study_id != study_id:
            raise AutoMLNotFoundError("AutoML trial not found.")
        return trial

    async def cancel(
        self, *, study_id: UUID, user_id: UUID, is_admin: bool
    ) -> tuple[AutoMLStudy, str]:
        current = await self.get_study(
            study_id=study_id, user_id=user_id, is_admin=is_admin
        )
        now = utc_now()
        if current.status is AutoMLStudyStatus.QUEUED:
            changed = await self._repository.conditionally_transition_study(
                study_id=study_id,
                expected_status=current.status,
                expected_version=current.state_version,
                new_status=AutoMLStudyStatus.CANCELLED,
                values={
                    "cancel_requested_at": now,
                    "cancelled_at": now,
                    "finished_at": now,
                },
            )
            if changed is None:
                await self._repository.rollback()
                raise AutoMLConflictError(
                    "The AutoML study changed before cancellation completed."
                )
            await self._repository.mark_queued_trials_cancelled(study_id, now)
            await self._repository.commit()
            outcome = "cancelled"
        elif (
            current.status is AutoMLStudyStatus.RUNNING
            and current.cancel_requested_at is None
        ):
            changed = await self._repository.request_study_cancellation(
                study_id=study_id,
                expected_version=current.state_version,
                requested_at=now,
            )
            if changed is None:
                await self._repository.rollback()
                raise AutoMLConflictError(
                    "The AutoML study changed before cancellation was requested."
                )
            await self._repository.mark_queued_trials_cancelled(study_id, now)
            await self._repository.commit()
            outcome = "requested"
        else:
            changed, outcome = current, "unchanged"
        emit_safe(
            logger,
            logging.INFO,
            "automl_study_cancellation",
            extra={"audit_event": "automl_study_cancellation", "outcome": outcome},
        )
        return changed, outcome

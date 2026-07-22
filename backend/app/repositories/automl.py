"""Async persistence boundary for AutoML management state."""

from dataclasses import dataclass
from datetime import datetime
from typing import cast as type_cast
from uuid import UUID

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.automl.models import AutoMLStudyStatus, AutoMLTrialStatus
from app.ml.domain import TaskType
from app.models.automl import AutoMLExecutionSlot, AutoMLStudy, AutoMLTrial


@dataclass(frozen=True, slots=True)
class AutoMLStudyPage:
    items: tuple[AutoMLStudy, ...]
    total: int


@dataclass(frozen=True, slots=True)
class AutoMLTrialPage:
    items: tuple[AutoMLTrial, ...]
    total: int


class AutoMLRepository:
    """Centralize owner-scoped reads and optimistic lifecycle writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_study(self, **values: object) -> AutoMLStudy:
        entity = AutoMLStudy(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_study_by_id(self, study_id: UUID) -> AutoMLStudy | None:
        return await self._session.get(AutoMLStudy, study_id)

    async def get_owned_study_by_id(
        self, study_id: UUID, owner_id: UUID
    ) -> AutoMLStudy | None:
        return (
            await self._session.execute(
                select(AutoMLStudy).where(
                    AutoMLStudy.id == study_id,
                    AutoMLStudy.requested_by_user_id == owner_id,
                )
            )
        ).scalar_one_or_none()

    async def find_by_scoped_idempotency_key(
        self, owner_id: UUID, key: str
    ) -> AutoMLStudy | None:
        return (
            await self._session.execute(
                select(AutoMLStudy).where(
                    AutoMLStudy.requested_by_user_id == owner_id,
                    AutoMLStudy.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()

    async def list_studies(
        self,
        *,
        owner_id: UUID | None,
        status: AutoMLStudyStatus | None,
        task_type: TaskType | None,
        plugin_id: str | None,
        requester_id: UUID | None,
        limit: int,
        offset: int,
    ) -> AutoMLStudyPage:
        statement = select(AutoMLStudy)
        if owner_id is not None:
            statement = statement.where(AutoMLStudy.requested_by_user_id == owner_id)
        if requester_id is not None:
            statement = statement.where(
                AutoMLStudy.requested_by_user_id == requester_id
            )
        if status is not None:
            statement = statement.where(AutoMLStudy.status == status)
        if task_type is not None:
            statement = statement.where(AutoMLStudy.task_type == task_type)
        if plugin_id is not None:
            # Exact JSON string matching is portable across SQLite and PostgreSQL.
            statement = statement.where(
                cast(AutoMLStudy.plugin_ids, String).contains(f'"{plugin_id}"')
            )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = (
            (
                await self._session.execute(
                    statement.order_by(
                        AutoMLStudy.created_at.desc(), AutoMLStudy.id.asc()
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return AutoMLStudyPage(tuple(rows), total)

    async def conditionally_transition_study(
        self,
        *,
        study_id: UUID,
        expected_status: AutoMLStudyStatus,
        expected_version: int,
        new_status: AutoMLStudyStatus,
        values: dict[str, object] | None = None,
    ) -> AutoMLStudy | None:
        statement = (
            update(AutoMLStudy)
            .where(
                AutoMLStudy.id == study_id,
                AutoMLStudy.status == expected_status,
                AutoMLStudy.state_version == expected_version,
            )
            .values(
                status=new_status,
                state_version=AutoMLStudy.state_version + 1,
                **(values or {}),
            )
            .returning(AutoMLStudy)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def request_study_cancellation(
        self, *, study_id: UUID, expected_version: int, requested_at: datetime
    ) -> AutoMLStudy | None:
        statement = (
            update(AutoMLStudy)
            .where(
                AutoMLStudy.id == study_id,
                AutoMLStudy.status == AutoMLStudyStatus.RUNNING,
                AutoMLStudy.state_version == expected_version,
                AutoMLStudy.cancel_requested_at.is_(None),
            )
            .values(
                cancel_requested_at=requested_at,
                state_version=AutoMLStudy.state_version + 1,
            )
            .returning(AutoMLStudy)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def mark_queued_trials_cancelled(
        self, study_id: UUID, cancelled_at: datetime
    ) -> int:
        result = await self._session.execute(
            update(AutoMLTrial)
            .where(
                AutoMLTrial.study_id == study_id,
                AutoMLTrial.status == AutoMLTrialStatus.QUEUED,
            )
            .values(
                status=AutoMLTrialStatus.CANCELLED,
                cancelled_at=cancelled_at,
                finished_at=cancelled_at,
                state_version=AutoMLTrial.state_version + 1,
            )
        )
        return int(type_cast(CursorResult[tuple[object]], result).rowcount)

    async def update_study_error(
        self,
        *,
        study_id: UUID,
        expected_version: int,
        error_code: str,
        safe_error_message: str,
    ) -> AutoMLStudy | None:
        statement = (
            update(AutoMLStudy)
            .where(
                AutoMLStudy.id == study_id,
                AutoMLStudy.state_version == expected_version,
            )
            .values(
                error_code=error_code,
                safe_error_message=safe_error_message,
                state_version=AutoMLStudy.state_version + 1,
            )
            .returning(AutoMLStudy)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def set_best_trial(
        self, *, study_id: UUID, trial_id: UUID, expected_version: int
    ) -> AutoMLStudy | None:
        statement = (
            update(AutoMLStudy)
            .where(
                AutoMLStudy.id == study_id,
                AutoMLStudy.state_version == expected_version,
                select(func.count())
                .select_from(AutoMLTrial)
                .where(AutoMLTrial.id == trial_id, AutoMLTrial.study_id == study_id)
                .scalar_subquery()
                == 1,
            )
            .values(best_trial_id=trial_id, state_version=AutoMLStudy.state_version + 1)
            .returning(AutoMLStudy)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def link_champion_training_job(
        self, *, study_id: UUID, training_job_id: UUID, expected_version: int
    ) -> AutoMLStudy | None:
        statement = (
            update(AutoMLStudy)
            .where(
                AutoMLStudy.id == study_id,
                AutoMLStudy.state_version == expected_version,
            )
            .values(
                champion_training_job_id=training_job_id,
                state_version=AutoMLStudy.state_version + 1,
            )
            .returning(AutoMLStudy)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create_trial(self, **values: object) -> AutoMLTrial:
        entity = AutoMLTrial(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def create_trials(
        self, values: list[dict[str, object]]
    ) -> tuple[AutoMLTrial, ...]:
        return tuple([await self.create_trial(**item) for item in values])

    async def get_trial_by_id(self, trial_id: UUID) -> AutoMLTrial | None:
        return await self._session.get(AutoMLTrial, trial_id)

    async def get_owned_trial_by_id(
        self, trial_id: UUID, owner_id: UUID
    ) -> AutoMLTrial | None:
        statement = (
            select(AutoMLTrial)
            .join(AutoMLStudy)
            .where(
                AutoMLTrial.id == trial_id, AutoMLStudy.requested_by_user_id == owner_id
            )
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_trials_for_study(
        self,
        *,
        study_id: UUID,
        status: AutoMLTrialStatus | None,
        plugin_id: str | None,
        limit: int,
        offset: int,
        metric_descending: bool = False,
    ) -> AutoMLTrialPage:
        statement = select(AutoMLTrial).where(AutoMLTrial.study_id == study_id)
        if status is not None:
            statement = statement.where(AutoMLTrial.status == status)
        if plugin_id is not None:
            statement = statement.where(AutoMLTrial.plugin_id == plugin_id)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        ordering = (
            AutoMLTrial.primary_metric_value.desc().nullslast()
            if metric_descending
            else AutoMLTrial.trial_number.asc()
        )
        rows = (
            (
                await self._session.execute(
                    statement.order_by(ordering, AutoMLTrial.id.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return AutoMLTrialPage(tuple(rows), total)

    async def conditionally_transition_trial(
        self,
        *,
        trial_id: UUID,
        expected_status: AutoMLTrialStatus,
        expected_version: int,
        new_status: AutoMLTrialStatus,
        values: dict[str, object] | None = None,
    ) -> AutoMLTrial | None:
        statement = (
            update(AutoMLTrial)
            .where(
                AutoMLTrial.id == trial_id,
                AutoMLTrial.status == expected_status,
                AutoMLTrial.state_version == expected_version,
            )
            .values(
                status=new_status,
                state_version=AutoMLTrial.state_version + 1,
                **(values or {}),
            )
            .returning(AutoMLTrial)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def update_trial_metrics(
        self,
        *,
        trial_id: UUID,
        expected_version: int,
        fold_metrics: list[dict[str, float]],
        aggregate_metrics: dict[str, float],
        primary_metric_value: float,
        duration_seconds: float,
    ) -> AutoMLTrial | None:
        statement = (
            update(AutoMLTrial)
            .where(
                AutoMLTrial.id == trial_id,
                AutoMLTrial.state_version == expected_version,
            )
            .values(
                fold_metrics=fold_metrics,
                aggregate_metrics=aggregate_metrics,
                primary_metric_value=primary_metric_value,
                duration_seconds=duration_seconds,
                state_version=AutoMLTrial.state_version + 1,
            )
            .returning(AutoMLTrial)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def update_trial_error(
        self,
        *,
        trial_id: UUID,
        expected_version: int,
        error_code: str,
        safe_error_message: str,
    ) -> AutoMLTrial | None:
        statement = (
            update(AutoMLTrial)
            .where(
                AutoMLTrial.id == trial_id,
                AutoMLTrial.state_version == expected_version,
            )
            .values(
                error_code=error_code,
                safe_error_message=safe_error_message,
                state_version=AutoMLTrial.state_version + 1,
            )
            .returning(AutoMLTrial)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def initialize_slots(self, count: int) -> tuple[AutoMLExecutionSlot, ...]:
        existing = {
            slot.slot_number
            for slot in (
                await self._session.execute(select(AutoMLExecutionSlot))
            ).scalars()
        }
        for number in range(1, count + 1):
            if number not in existing:
                self._session.add(AutoMLExecutionSlot(slot_number=number))
        await self._session.flush()
        return await self.list_slots()

    async def list_slots(self) -> tuple[AutoMLExecutionSlot, ...]:
        return tuple(
            (
                await self._session.execute(
                    select(AutoMLExecutionSlot).order_by(
                        AutoMLExecutionSlot.slot_number
                    )
                )
            )
            .scalars()
            .all()
        )

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

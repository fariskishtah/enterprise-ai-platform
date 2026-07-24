"""Typed persistence for prediction events and reference profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.ml.base import TrainerKey
from app.ml.domain import TaskType
from app.ml.jobs.models import (
    TrainingJobSpec,
    TrainingJobStatus,
    parse_training_job_spec,
)
from app.ml.monitoring.exceptions import MonitoringDataError
from app.ml.monitoring.models import (
    ModelReferenceProfile,
    OperationalAggregate,
    PredictionEvent,
    PredictionEventPage,
    PredictionEventStatus,
)
from app.ml.monitoring.serialization import (
    feature_reference_profiles_payload,
    feature_request_profiles_payload,
    parse_feature_reference_profiles,
    parse_feature_request_profiles,
    parse_prediction_reference_profile,
    parse_prediction_request_profile,
    prediction_reference_profile_payload,
    prediction_request_profile_payload,
)
from app.models.ai_governance import TrainingJob
from app.models.ai_monitoring import (
    ModelReferenceProfileEntity,
    PredictionEventEntity,
)
from app.repositories.tenant import company_for_training_job, company_for_user
from app.utils.security import as_utc


@dataclass(frozen=True, slots=True)
class MissingReferenceProfileJob:
    """Successful job input needed for bounded profile reconciliation."""

    id: UUID
    key: TrainerKey
    registered_model_name: str
    registered_model_version: str
    specification: TrainingJobSpec


class PredictionMonitoringRepository:
    """Own monitoring SQL and return only immutable application records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_event(self, event: PredictionEvent) -> PredictionEvent:
        """Persist one completed event containing only safe summaries."""
        entity = PredictionEventEntity(
            id=event.id,
            company_id=await company_for_user(
                self._session, event.requested_by_user_id
            ),
            requested_by_user_id=event.requested_by_user_id,
            registered_model_name=event.registered_model_name,
            requested_model_reference=event.requested_model_reference,
            resolved_model_version=event.resolved_model_version,
            resolved_aliases=list(event.resolved_aliases),
            algorithm=event.key.algorithm,
            task_type=event.key.task_type,
            status=event.status,
            row_count=event.row_count,
            feature_count=event.feature_count,
            duration_ms=event.duration_ms,
            feature_profile=feature_request_profiles_payload(event.feature_profile),
            prediction_profile=(
                prediction_request_profile_payload(event.prediction_profile)
                if event.prediction_profile is not None
                else None
            ),
            error_code=event.error_code,
            safe_error_message=event.safe_error_message,
            correlation_id=event.correlation_id,
            created_at=event.created_at,
            completed_at=event.completed_at,
        )
        self._session.add(entity)
        await self._session.flush()
        return _event_record(entity)

    async def get_event(self, event_id: UUID) -> PredictionEvent | None:
        """Return one event without applying transport authorization policy."""
        entity = await self._session.get(PredictionEventEntity, event_id)
        return _event_record(entity) if entity is not None else None

    async def list_events(
        self,
        *,
        registered_model_name: str | None,
        resolved_model_version: str | None,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> PredictionEventPage:
        """Return a bounded filtered page ordered newest first."""
        statement = self._event_filter(
            registered_model_name=registered_model_name,
            resolved_model_version=resolved_model_version,
            task_type=task_type,
            status=status,
            start_at=start_at,
            end_at=end_at,
        )
        count = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery()),
        )
        result = await self._session.execute(
            statement.order_by(
                PredictionEventEntity.created_at.desc(),
                PredictionEventEntity.id.asc(),
            )
            .limit(limit)
            .offset(offset),
        )
        return PredictionEventPage(
            items=tuple(_event_record(entity) for entity in result.scalars()),
            total=count or 0,
        )

    async def aggregate_operations(
        self,
        *,
        registered_model_name: str,
        resolved_model_version: str,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime,
        end_at: datetime,
    ) -> OperationalAggregate:
        """Calculate portable operational totals inside the database."""
        conditions = self._event_conditions(
            registered_model_name=registered_model_name,
            resolved_model_version=resolved_model_version,
            task_type=task_type,
            status=status,
            start_at=start_at,
            end_at=end_at,
        )
        row = (
            await self._session.execute(
                select(
                    func.count(PredictionEventEntity.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    PredictionEventEntity.status
                                    == PredictionEventStatus.SUCCEEDED,
                                    1,
                                ),
                                else_=0,
                            ),
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    PredictionEventEntity.status
                                    == PredictionEventStatus.FAILED,
                                    1,
                                ),
                                else_=0,
                            ),
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(PredictionEventEntity.duration_ms), 0.0),
                    func.min(PredictionEventEntity.duration_ms),
                    func.max(PredictionEventEntity.duration_ms),
                    func.coalesce(func.sum(PredictionEventEntity.row_count), 0),
                ).where(*conditions),
            )
        ).one()
        errors = await self._session.execute(
            select(
                PredictionEventEntity.error_code,
                func.count(PredictionEventEntity.id),
            )
            .where(
                *conditions,
                PredictionEventEntity.status == PredictionEventStatus.FAILED,
                PredictionEventEntity.error_code.is_not(None),
            )
            .group_by(PredictionEventEntity.error_code),
        )
        return OperationalAggregate(
            request_count=int(row[0]),
            success_count=int(row[1]),
            failure_count=int(row[2]),
            duration_total_ms=float(row[3]),
            minimum_duration_ms=(float(row[4]) if row[4] is not None else None),
            maximum_duration_ms=(float(row[5]) if row[5] is not None else None),
            total_predicted_rows=int(row[6]),
            failures_by_error_code={
                error_code: int(error_count)
                for error_code, error_count in errors
                if error_code is not None
            },
        )

    async def list_durations(
        self,
        *,
        registered_model_name: str,
        resolved_model_version: str,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[float, ...]:
        """Select the newest matching events deterministically, then sort latency."""
        conditions = self._event_conditions(
            registered_model_name=registered_model_name,
            resolved_model_version=resolved_model_version,
            task_type=task_type,
            status=status,
            start_at=start_at,
            end_at=end_at,
        )
        result = await self._session.execute(
            select(PredictionEventEntity.duration_ms)
            .where(*conditions)
            .order_by(
                PredictionEventEntity.created_at.desc(),
                PredictionEventEntity.id.asc(),
            )
            .limit(limit),
        )
        return tuple(sorted(float(value) for value in result.scalars()))

    async def list_window_events(
        self,
        *,
        registered_model_name: str,
        resolved_model_version: str,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> PredictionEventPage:
        """Return the newest matching window events with deterministic tie-breaking."""
        return await self.list_events(
            registered_model_name=registered_model_name,
            resolved_model_version=resolved_model_version,
            task_type=None,
            status=None,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=0,
        )

    async def get_reference_profile(
        self,
        registered_model_name: str,
        model_version: str,
    ) -> ModelReferenceProfile | None:
        """Return one exact-version immutable reference profile."""
        statement = select(ModelReferenceProfileEntity).where(
            ModelReferenceProfileEntity.registered_model_name == registered_model_name,
            ModelReferenceProfileEntity.model_version == model_version,
        )
        entity = (await self._session.execute(statement)).scalar_one_or_none()
        return _reference_record(entity) if entity is not None else None

    async def create_reference_profile(
        self,
        profile: ModelReferenceProfile,
    ) -> ModelReferenceProfile:
        """Create once by version or return the existing profile idempotently."""
        existing = await self.get_reference_profile(
            profile.registered_model_name,
            profile.model_version,
        )
        if existing is not None:
            return existing
        entity = ModelReferenceProfileEntity(
            id=profile.id,
            company_id=await company_for_training_job(
                self._session, profile.training_job_id
            ),
            registered_model_name=profile.registered_model_name,
            model_version=profile.model_version,
            algorithm=profile.key.algorithm,
            task_type=profile.key.task_type,
            source=profile.source,
            feature_count=profile.feature_count,
            feature_profiles=feature_reference_profiles_payload(profile.features),
            prediction_profile=prediction_reference_profile_payload(
                profile.prediction,
            ),
            sample_count=profile.sample_count,
            training_job_id=profile.training_job_id,
            created_at=profile.created_at,
        )
        self._session.add(entity)
        await self._session.flush()
        return _reference_record(entity)

    async def list_missing_reference_profiles(
        self,
        *,
        limit: int,
    ) -> tuple[MissingReferenceProfileJob, ...]:
        """Find bounded successful jobs whose exact version lacks a profile."""
        statement = (
            select(TrainingJob)
            .outerjoin(
                ModelReferenceProfileEntity,
                (
                    ModelReferenceProfileEntity.registered_model_name
                    == TrainingJob.registered_model_name
                )
                & (
                    ModelReferenceProfileEntity.model_version
                    == TrainingJob.registered_model_version
                ),
            )
            .where(
                TrainingJob.status == TrainingJobStatus.SUCCEEDED,
                TrainingJob.registered_model_version.is_not(None),
                ModelReferenceProfileEntity.id.is_(None),
            )
            .order_by(TrainingJob.finished_at.asc(), TrainingJob.id.asc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        records: list[MissingReferenceProfileJob] = []
        for entity in result.scalars():
            if entity.registered_model_version is None:
                continue
            records.append(
                MissingReferenceProfileJob(
                    id=entity.id,
                    key=TrainerKey(entity.algorithm, entity.task_type),
                    registered_model_name=entity.registered_model_name,
                    registered_model_version=entity.registered_model_version,
                    specification=parse_training_job_spec(
                        entity.task_type,
                        entity.algorithm,
                        entity.specification,
                    ),
                ),
            )
        return tuple(records)

    async def count_events_before(self, cutoff: datetime) -> int:
        """Count events eligible for a retention dry run."""
        count = await self._session.scalar(
            select(func.count(PredictionEventEntity.id)).where(
                PredictionEventEntity.created_at < cutoff,
            ),
        )
        return count or 0

    async def delete_events_before(
        self,
        *,
        cutoff: datetime,
        limit: int,
    ) -> int:
        """Delete at most one bounded oldest-event batch."""
        identifiers = (
            select(PredictionEventEntity.id)
            .where(PredictionEventEntity.created_at < cutoff)
            .order_by(
                PredictionEventEntity.created_at.asc(),
                PredictionEventEntity.id.asc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(
            delete(PredictionEventEntity)
            .where(
                PredictionEventEntity.id.in_(identifiers),
            )
            .returning(PredictionEventEntity.id),
        )
        return len(tuple(result.scalars()))

    async def commit(self) -> None:
        """Commit the active monitoring transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active monitoring transaction."""
        await self._session.rollback()

    @staticmethod
    def _event_filter(
        *,
        registered_model_name: str | None,
        resolved_model_version: str | None,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> Select[tuple[PredictionEventEntity]]:
        return select(PredictionEventEntity).where(
            *PredictionMonitoringRepository._event_conditions(
                registered_model_name=registered_model_name,
                resolved_model_version=resolved_model_version,
                task_type=task_type,
                status=status,
                start_at=start_at,
                end_at=end_at,
            ),
        )

    @staticmethod
    def _event_conditions(
        *,
        registered_model_name: str | None,
        resolved_model_version: str | None,
        task_type: TaskType | None,
        status: PredictionEventStatus | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if registered_model_name is not None:
            conditions.append(
                PredictionEventEntity.registered_model_name == registered_model_name,
            )
        if resolved_model_version is not None:
            conditions.append(
                PredictionEventEntity.resolved_model_version == resolved_model_version,
            )
        if task_type is not None:
            conditions.append(PredictionEventEntity.task_type == task_type)
        if status is not None:
            conditions.append(PredictionEventEntity.status == status)
        if start_at is not None:
            conditions.append(PredictionEventEntity.created_at >= start_at)
        if end_at is not None:
            conditions.append(PredictionEventEntity.created_at < end_at)
        return conditions


def _event_record(entity: PredictionEventEntity) -> PredictionEvent:
    aliases = entity.resolved_aliases
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) for alias in aliases
    ):
        raise MonitoringDataError("Persisted resolved aliases are invalid.")
    return PredictionEvent(
        id=entity.id,
        requested_by_user_id=entity.requested_by_user_id,
        registered_model_name=entity.registered_model_name,
        requested_model_reference=entity.requested_model_reference,
        resolved_model_version=entity.resolved_model_version,
        resolved_aliases=tuple(aliases),
        key=TrainerKey(entity.algorithm, entity.task_type),
        status=entity.status,
        row_count=entity.row_count,
        feature_count=entity.feature_count,
        duration_ms=entity.duration_ms,
        feature_profile=parse_feature_request_profiles(entity.feature_profile),
        prediction_profile=(
            parse_prediction_request_profile(entity.prediction_profile)
            if entity.prediction_profile is not None
            else None
        ),
        error_code=entity.error_code,
        safe_error_message=entity.safe_error_message,
        correlation_id=entity.correlation_id,
        created_at=as_utc(entity.created_at),
        completed_at=as_utc(entity.completed_at),
    )


def _reference_record(entity: ModelReferenceProfileEntity) -> ModelReferenceProfile:
    return ModelReferenceProfile(
        id=entity.id,
        registered_model_name=entity.registered_model_name,
        model_version=entity.model_version,
        key=TrainerKey(entity.algorithm, entity.task_type),
        source=entity.source,
        feature_count=entity.feature_count,
        features=parse_feature_reference_profiles(entity.feature_profiles),
        prediction=parse_prediction_reference_profile(entity.prediction_profile),
        sample_count=entity.sample_count,
        training_job_id=entity.training_job_id,
        created_at=as_utc(entity.created_at),
    )

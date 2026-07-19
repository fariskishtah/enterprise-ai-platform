"""Persistence boundary for completed model monitoring evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.ml.base import TrainerKey
from app.ml.jobs import TrainingJobStatus
from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringEvaluationPage,
    MonitoringEvaluationStatus,
)
from app.models.ai_governance import TrainingJob
from app.models.ai_retraining import ModelRetrainingAudit, ModelRetrainingRequest
from app.models.monitoring_orchestration import ModelMonitoringEvaluationEntity
from app.utils.security import as_utc


@dataclass(frozen=True, slots=True)
class RegisteredModelCandidate:
    registered_model_name: str


class MonitoringEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, evaluation: ModelMonitoringEvaluation
    ) -> ModelMonitoringEvaluation:
        entity = ModelMonitoringEvaluationEntity(
            id=evaluation.id,
            registered_model_name=evaluation.registered_model_name,
            model_version=evaluation.model_version,
            model_alias=evaluation.model_alias,
            algorithm=evaluation.key.algorithm,
            task_type=evaluation.key.task_type,
            window_start=evaluation.window_start,
            window_end=evaluation.window_end,
            evaluated_sample_count=evaluation.evaluated_sample_count,
            successful_prediction_count=evaluation.successful_prediction_count,
            failed_prediction_count=evaluation.failed_prediction_count,
            data_quality_status=evaluation.data_quality_status,
            feature_drift_status=evaluation.feature_drift_status,
            prediction_drift_status=evaluation.prediction_drift_status,
            operational_health_status=evaluation.operational_health_status,
            overall_status=evaluation.overall_status,
            report_schema_version=evaluation.report_schema_version,
            report=dict(evaluation.report),
            warning_count=evaluation.warning_count,
            critical_count=evaluation.critical_count,
            trigger=evaluation.trigger,
            idempotency_key=evaluation.idempotency_key,
            created_at=evaluation.created_at,
            updated_at=evaluation.updated_at,
        )
        self._session.add(entity)
        await self._session.flush()
        return _record(entity)

    async def get(self, evaluation_id: UUID) -> ModelMonitoringEvaluation | None:
        entity = await self._session.get(ModelMonitoringEvaluationEntity, evaluation_id)
        return _record(entity) if entity is not None else None

    async def get_by_idempotency(
        self, idempotency_key: str
    ) -> ModelMonitoringEvaluation | None:
        entity = (
            await self._session.execute(
                select(ModelMonitoringEvaluationEntity).where(
                    ModelMonitoringEvaluationEntity.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def get_by_window(
        self,
        *,
        registered_model_name: str,
        model_version: str,
        window_start: datetime,
        window_end: datetime,
    ) -> ModelMonitoringEvaluation | None:
        entity = (
            await self._session.execute(
                select(ModelMonitoringEvaluationEntity).where(
                    ModelMonitoringEvaluationEntity.registered_model_name
                    == registered_model_name,
                    ModelMonitoringEvaluationEntity.model_version == model_version,
                    ModelMonitoringEvaluationEntity.window_start == window_start,
                    ModelMonitoringEvaluationEntity.window_end == window_end,
                )
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def latest(
        self, *, registered_model_name: str, model_version: str
    ) -> ModelMonitoringEvaluation | None:
        entity = (
            await self._session.execute(
                select(ModelMonitoringEvaluationEntity)
                .where(
                    ModelMonitoringEvaluationEntity.registered_model_name
                    == registered_model_name,
                    ModelMonitoringEvaluationEntity.model_version == model_version,
                )
                .order_by(
                    ModelMonitoringEvaluationEntity.window_end.desc(),
                    ModelMonitoringEvaluationEntity.id.asc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def list(
        self,
        *,
        registered_model_name: str | None,
        model_version: str | None,
        overall_status: MonitoringEvaluationStatus | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> MonitoringEvaluationPage:
        conditions: list[ColumnElement[bool]] = []
        if registered_model_name is not None:
            conditions.append(
                ModelMonitoringEvaluationEntity.registered_model_name
                == registered_model_name
            )
        if model_version is not None:
            conditions.append(
                ModelMonitoringEvaluationEntity.model_version == model_version
            )
        if overall_status is not None:
            conditions.append(
                ModelMonitoringEvaluationEntity.overall_status == overall_status
            )
        if start_at is not None:
            conditions.append(ModelMonitoringEvaluationEntity.window_end >= start_at)
        if end_at is not None:
            conditions.append(ModelMonitoringEvaluationEntity.window_end < end_at)
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(ModelMonitoringEvaluationEntity)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(ModelMonitoringEvaluationEntity)
            .where(*conditions)
            .order_by(
                ModelMonitoringEvaluationEntity.window_end.desc(),
                ModelMonitoringEvaluationEntity.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return MonitoringEvaluationPage(
            tuple(_record(item) for item in result.scalars()), total
        )

    async def list_registered_model_names(self, *, limit: int) -> tuple[str, ...]:
        result = await self._session.execute(
            select(TrainingJob.registered_model_name)
            .where(
                TrainingJob.status == TrainingJobStatus.SUCCEEDED,
                TrainingJob.registered_model_version.is_not(None),
            )
            .distinct()
            .order_by(TrainingJob.registered_model_name)
            .limit(limit)
        )
        return tuple(result.scalars())

    async def count_before(self, cutoff: datetime) -> int:
        safe_to_delete = _safe_retention_condition()
        value = await self._session.scalar(
            select(func.count(ModelMonitoringEvaluationEntity.id)).where(
                ModelMonitoringEvaluationEntity.created_at < cutoff,
                safe_to_delete,
            )
        )
        return value or 0

    async def delete_before(self, *, cutoff: datetime, limit: int) -> int:
        identifiers = (
            select(ModelMonitoringEvaluationEntity.id)
            .where(
                ModelMonitoringEvaluationEntity.created_at < cutoff,
                _safe_retention_condition(),
            )
            .order_by(
                ModelMonitoringEvaluationEntity.created_at,
                ModelMonitoringEvaluationEntity.id,
            )
            .limit(limit)
        )
        result = await self._session.execute(
            delete(ModelMonitoringEvaluationEntity)
            .where(ModelMonitoringEvaluationEntity.id.in_(identifiers))
            .returning(ModelMonitoringEvaluationEntity.id)
        )
        return len(tuple(result.scalars()))

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


def _record(entity: ModelMonitoringEvaluationEntity) -> ModelMonitoringEvaluation:
    return ModelMonitoringEvaluation(
        id=entity.id,
        registered_model_name=entity.registered_model_name,
        model_version=entity.model_version,
        model_alias=entity.model_alias,
        key=TrainerKey(entity.algorithm, entity.task_type),
        window_start=as_utc(entity.window_start),
        window_end=as_utc(entity.window_end),
        evaluated_sample_count=entity.evaluated_sample_count,
        successful_prediction_count=entity.successful_prediction_count,
        failed_prediction_count=entity.failed_prediction_count,
        data_quality_status=entity.data_quality_status,
        feature_drift_status=entity.feature_drift_status,
        prediction_drift_status=entity.prediction_drift_status,
        operational_health_status=entity.operational_health_status,
        overall_status=entity.overall_status,
        report_schema_version=entity.report_schema_version,
        report=entity.report,
        warning_count=entity.warning_count,
        critical_count=entity.critical_count,
        trigger=entity.trigger,
        idempotency_key=entity.idempotency_key,
        created_at=as_utc(entity.created_at),
        updated_at=as_utc(entity.updated_at),
    )


def _safe_retention_condition() -> ColumnElement[bool]:
    """Never delete monitoring evidence referenced by retraining governance."""
    request_exists = select(ModelRetrainingRequest.id).where(
        ModelRetrainingRequest.monitoring_evaluation_id
        == ModelMonitoringEvaluationEntity.id
    )
    audit_exists = select(ModelRetrainingAudit.id).where(
        ModelRetrainingAudit.monitoring_evaluation_id
        == ModelMonitoringEvaluationEntity.id
    )
    return ~request_exists.exists() & ~audit_exists.exists()

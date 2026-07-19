"""Persistent deduplicated monitoring alerts and cross-process job locks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.ml.monitoring.evaluation_models import (
    MonitoringAlert,
    MonitoringAlertPage,
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
)
from app.models.monitoring_orchestration import (
    MonitoringAlertEntity,
    MonitoringJobLockEntity,
)
from app.utils.security import as_utc


class MonitoringAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, alert_id: UUID) -> MonitoringAlert | None:
        entity = await self._session.get(MonitoringAlertEntity, alert_id)
        return _record(entity) if entity is not None else None

    async def get_by_deduplication(self, key: str) -> MonitoringAlert | None:
        entity = (
            await self._session.execute(
                select(MonitoringAlertEntity).where(
                    MonitoringAlertEntity.deduplication_key == key
                )
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def create(self, alert: MonitoringAlert) -> MonitoringAlert:
        entity = MonitoringAlertEntity(
            id=alert.id,
            alert_type=alert.alert_type,
            severity=alert.severity,
            registered_model_name=alert.registered_model_name,
            model_version=alert.model_version,
            monitoring_evaluation_id=alert.monitoring_evaluation_id,
            title=alert.title,
            safe_summary=alert.safe_summary,
            deduplication_key=alert.deduplication_key,
            status=alert.status,
            first_detected_at=alert.first_detected_at,
            last_detected_at=alert.last_detected_at,
            occurrence_count=alert.occurrence_count,
            acknowledged_at=alert.acknowledged_at,
            acknowledged_by_user_id=alert.acknowledged_by_user_id,
            resolved_at=alert.resolved_at,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
        )
        self._session.add(entity)
        await self._session.flush()
        return _record(entity)

    async def redetect(
        self,
        *,
        alert_id: UUID,
        severity: MonitoringAlertSeverity,
        monitoring_evaluation_id: UUID | None,
        detected_at: datetime,
        title: str,
        safe_summary: str,
    ) -> MonitoringAlert | None:
        entity = (
            await self._session.execute(
                update(MonitoringAlertEntity)
                .where(MonitoringAlertEntity.id == alert_id)
                .values(
                    severity=severity,
                    monitoring_evaluation_id=monitoring_evaluation_id,
                    title=title,
                    safe_summary=safe_summary,
                    status=MonitoringAlertStatus.OPEN,
                    last_detected_at=detected_at,
                    occurrence_count=MonitoringAlertEntity.occurrence_count + 1,
                    acknowledged_at=None,
                    acknowledged_by_user_id=None,
                    resolved_at=None,
                    updated_at=detected_at,
                )
                .returning(MonitoringAlertEntity)
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def list(
        self,
        *,
        registered_model_name: str | None,
        model_version: str | None,
        severity: MonitoringAlertSeverity | None,
        status: MonitoringAlertStatus | None,
        limit: int,
        offset: int,
    ) -> MonitoringAlertPage:
        conditions: list[ColumnElement[bool]] = []
        if registered_model_name is not None:
            conditions.append(
                MonitoringAlertEntity.registered_model_name == registered_model_name
            )
        if model_version is not None:
            conditions.append(MonitoringAlertEntity.model_version == model_version)
        if severity is not None:
            conditions.append(MonitoringAlertEntity.severity == severity)
        if status is not None:
            conditions.append(MonitoringAlertEntity.status == status)
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(MonitoringAlertEntity)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(MonitoringAlertEntity)
            .where(*conditions)
            .order_by(
                MonitoringAlertEntity.last_detected_at.desc(),
                MonitoringAlertEntity.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return MonitoringAlertPage(
            tuple(_record(item) for item in result.scalars()), total
        )

    async def acknowledge(
        self, *, alert_id: UUID, actor_id: UUID, acknowledged_at: datetime
    ) -> MonitoringAlert | None:
        entity = (
            await self._session.execute(
                update(MonitoringAlertEntity)
                .where(
                    MonitoringAlertEntity.id == alert_id,
                    MonitoringAlertEntity.status == MonitoringAlertStatus.OPEN,
                )
                .values(
                    status=MonitoringAlertStatus.ACKNOWLEDGED,
                    acknowledged_at=acknowledged_at,
                    acknowledged_by_user_id=actor_id,
                    updated_at=acknowledged_at,
                )
                .returning(MonitoringAlertEntity)
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def resolve(
        self, *, alert_id: UUID, resolved_at: datetime
    ) -> MonitoringAlert | None:
        entity = (
            await self._session.execute(
                update(MonitoringAlertEntity)
                .where(
                    MonitoringAlertEntity.id == alert_id,
                    MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
                )
                .values(
                    status=MonitoringAlertStatus.RESOLVED,
                    resolved_at=resolved_at,
                    updated_at=resolved_at,
                )
                .returning(MonitoringAlertEntity)
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def resolve_types(
        self,
        *,
        registered_model_name: str,
        model_version: str,
        alert_types: frozenset[MonitoringAlertType],
        resolved_at: datetime,
    ) -> tuple[MonitoringAlert, ...]:
        if not alert_types:
            return ()
        result = await self._session.execute(
            update(MonitoringAlertEntity)
            .where(
                MonitoringAlertEntity.registered_model_name == registered_model_name,
                MonitoringAlertEntity.model_version == model_version,
                MonitoringAlertEntity.alert_type.in_(alert_types),
                MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
            )
            .values(
                status=MonitoringAlertStatus.RESOLVED,
                resolved_at=resolved_at,
                updated_at=resolved_at,
            )
            .returning(MonitoringAlertEntity)
        )
        return tuple(_record(entity) for entity in result.scalars())

    async def resolve_stale(
        self, *, last_detected_before: datetime, limit: int
    ) -> tuple[MonitoringAlert, ...]:
        identifiers = (
            select(MonitoringAlertEntity.id)
            .where(
                MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
                MonitoringAlertEntity.last_detected_at < last_detected_before,
            )
            .order_by(MonitoringAlertEntity.last_detected_at, MonitoringAlertEntity.id)
            .limit(limit)
        )
        result = await self._session.execute(
            update(MonitoringAlertEntity)
            .where(MonitoringAlertEntity.id.in_(identifiers))
            .values(
                status=MonitoringAlertStatus.RESOLVED,
                resolved_at=last_detected_before,
                updated_at=last_detected_before,
            )
            .returning(MonitoringAlertEntity)
        )
        return tuple(_record(entity) for entity in result.scalars())

    async def acquire_lock(
        self,
        *,
        lock_key: str,
        owner_id: str,
        acquired_at: datetime,
        expires_at: datetime,
    ) -> bool:
        await self._session.execute(
            delete(MonitoringJobLockEntity).where(
                MonitoringJobLockEntity.lock_key == lock_key,
                MonitoringJobLockEntity.expires_at <= acquired_at,
            )
        )
        existing = await self._session.get(MonitoringJobLockEntity, lock_key)
        if existing is not None:
            return False
        self._session.add(
            MonitoringJobLockEntity(
                lock_key=lock_key,
                owner_id=owner_id,
                acquired_at=acquired_at,
                expires_at=expires_at,
            )
        )
        await self._session.flush()
        return True

    async def release_lock(self, *, lock_key: str, owner_id: str) -> bool:
        result = await self._session.execute(
            delete(MonitoringJobLockEntity)
            .where(
                MonitoringJobLockEntity.lock_key == lock_key,
                MonitoringJobLockEntity.owner_id == owner_id,
            )
            .returning(MonitoringJobLockEntity.lock_key)
        )
        return result.scalar_one_or_none() is not None

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


def _record(entity: MonitoringAlertEntity) -> MonitoringAlert:
    return MonitoringAlert(
        id=entity.id,
        alert_type=entity.alert_type,
        severity=entity.severity,
        registered_model_name=entity.registered_model_name,
        model_version=entity.model_version,
        monitoring_evaluation_id=entity.monitoring_evaluation_id,
        title=entity.title,
        safe_summary=entity.safe_summary,
        deduplication_key=entity.deduplication_key,
        status=entity.status,
        first_detected_at=as_utc(entity.first_detected_at),
        last_detected_at=as_utc(entity.last_detected_at),
        occurrence_count=entity.occurrence_count,
        acknowledged_at=(
            as_utc(entity.acknowledged_at) if entity.acknowledged_at else None
        ),
        acknowledged_by_user_id=entity.acknowledged_by_user_id,
        resolved_at=as_utc(entity.resolved_at) if entity.resolved_at else None,
        created_at=as_utc(entity.created_at),
        updated_at=as_utc(entity.updated_at),
    )

"""Persistence for observed prediction outcomes and mature bounded joins."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.monitoring.evaluation_models import PredictionOutcome
from app.ml.monitoring.models import PredictionEvent
from app.models.ai_monitoring import PredictionEventEntity
from app.models.monitoring_orchestration import PredictionOutcomeEntity
from app.repositories.ai_monitoring import _event_record
from app.repositories.tenant import company_for_prediction_event
from app.utils.security import as_utc


class PredictionOutcomeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_event(self, prediction_event_id: UUID) -> PredictionOutcome | None:
        entity = (
            await self._session.execute(
                select(PredictionOutcomeEntity).where(
                    PredictionOutcomeEntity.prediction_event_id == prediction_event_id
                )
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def get_by_external_reference(self, key: str) -> PredictionOutcome | None:
        entity = (
            await self._session.execute(
                select(PredictionOutcomeEntity).where(
                    PredictionOutcomeEntity.external_reference_key == key
                )
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def create(self, outcome: PredictionOutcome) -> PredictionOutcome:
        entity = PredictionOutcomeEntity(
            id=outcome.id,
            company_id=await company_for_prediction_event(
                self._session, outcome.prediction_event_id
            ),
            prediction_event_id=outcome.prediction_event_id,
            outcome_type=outcome.outcome_type,
            actual_value={"value": outcome.actual_value},
            observed_at=outcome.observed_at,
            source=outcome.source,
            label_maturity_at=outcome.label_maturity_at,
            safe_metadata=dict(outcome.safe_metadata),
            external_reference_key=outcome.external_reference_key,
            created_at=outcome.created_at,
            updated_at=outcome.updated_at,
        )
        self._session.add(entity)
        await self._session.flush()
        return _record(entity)

    async def update(self, outcome: PredictionOutcome) -> PredictionOutcome | None:
        entity = (
            await self._session.execute(
                update(PredictionOutcomeEntity)
                .where(PredictionOutcomeEntity.id == outcome.id)
                .values(
                    outcome_type=outcome.outcome_type,
                    actual_value={"value": outcome.actual_value},
                    observed_at=outcome.observed_at,
                    source=outcome.source,
                    label_maturity_at=outcome.label_maturity_at,
                    safe_metadata=dict(outcome.safe_metadata),
                    external_reference_key=outcome.external_reference_key,
                    updated_at=outcome.updated_at,
                )
                .returning(PredictionOutcomeEntity)
            )
        ).scalar_one_or_none()
        return _record(entity) if entity is not None else None

    async def list_mature(
        self,
        *,
        registered_model_name: str,
        model_version: str,
        mature_at: datetime,
        limit: int,
    ) -> tuple[tuple[PredictionOutcome, PredictionEvent], ...]:
        result = await self._session.execute(
            select(PredictionOutcomeEntity, PredictionEventEntity)
            .join(
                PredictionEventEntity,
                PredictionEventEntity.id == PredictionOutcomeEntity.prediction_event_id,
            )
            .where(
                PredictionEventEntity.registered_model_name == registered_model_name,
                PredictionEventEntity.resolved_model_version == model_version,
                PredictionOutcomeEntity.label_maturity_at <= mature_at,
            )
            .order_by(
                PredictionOutcomeEntity.label_maturity_at,
                PredictionOutcomeEntity.id,
            )
            .limit(limit)
        )
        return tuple(
            (_record(outcome), _event_record(event)) for outcome, event in result
        )

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


def _record(entity: PredictionOutcomeEntity) -> PredictionOutcome:
    raw_value = entity.actual_value.get("value")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise ValueError("Persisted prediction outcome value is invalid.")
    return PredictionOutcome(
        id=entity.id,
        prediction_event_id=entity.prediction_event_id,
        outcome_type=entity.outcome_type,
        actual_value=raw_value,
        observed_at=as_utc(entity.observed_at),
        source=entity.source,
        label_maturity_at=as_utc(entity.label_maturity_at),
        safe_metadata=entity.safe_metadata,
        external_reference_key=entity.external_reference_key,
        created_at=as_utc(entity.created_at),
        updated_at=as_utc(entity.updated_at),
    )

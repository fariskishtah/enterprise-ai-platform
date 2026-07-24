"""Append-only tenant audit persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AuditEvent


class AuditRepository:
    """Expose inserts and bounded reads; deliberately no update/delete methods."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, **values: object) -> AuditEvent:
        event = AuditEvent(**values)
        self._session.add(event)
        await self._session.flush()
        await self._session.refresh(event)
        return event

    async def list_events(
        self,
        *,
        company_id: UUID,
        actor_user_id: UUID | None,
        action: str | None,
        result: str | None,
        resource_type: str | None,
        resource_id: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditEvent], int]:
        statement = select(AuditEvent).where(AuditEvent.company_id == company_id)
        filters = (
            (actor_user_id, AuditEvent.actor_user_id),
            (action, AuditEvent.action),
            (result, AuditEvent.result),
            (resource_type, AuditEvent.resource_type),
            (resource_id, AuditEvent.resource_id),
        )
        for value, column in filters:
            if value is not None:
                statement = statement.where(column == value)
        if start_at is not None:
            statement = statement.where(AuditEvent.occurred_at >= start_at)
        if end_at is not None:
            statement = statement.where(AuditEvent.occurred_at <= end_at)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        items = list(
            (
                await self._session.execute(
                    statement.order_by(
                        AuditEvent.occurred_at.desc(), AuditEvent.id.desc()
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return items, total

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

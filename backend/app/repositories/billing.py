"""Persistence boundaries for tenant payments and provider callbacks."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import BillingWebhookEvent, Payment
from app.models.manufacturing import Company


class BillingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def company_is_billable(self, company_id: UUID) -> bool:
        return (
            await self._session.scalar(
                select(Company.id).where(
                    Company.id == company_id, Company.deleted_at.is_(None)
                )
            )
            is not None
        )

    async def get_payment(
        self, payment_id: UUID, *, lock: bool = False
    ) -> Payment | None:
        statement: Select[tuple[Payment]] = select(Payment).where(
            Payment.id == payment_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_company_payment(
        self, payment_id: UUID, company_id: UUID, *, lock: bool = False
    ) -> Payment | None:
        statement: Select[tuple[Payment]] = select(Payment).where(
            Payment.id == payment_id,
            Payment.company_id == company_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_by_idempotency(
        self, company_id: UUID, idempotency_key: str
    ) -> Payment | None:
        return await self._session.scalar(
            select(Payment).where(
                Payment.company_id == company_id,
                Payment.idempotency_key == idempotency_key,
            )
        )

    def add_payment(self, payment: Payment) -> None:
        self._session.add(payment)

    async def claim_payment_retry(self, payment_id: UUID) -> bool:
        result = cast(
            CursorResult[object],
            await self._session.execute(
                update(Payment)
                .where(Payment.id == payment_id, Payment.status == "provider_error")
                .values(status="creating", failure_code=None)
            ),
        )
        return bool(result.rowcount)

    async def get_event_by_provider_id(
        self, provider: str, provider_event_id: str
    ) -> BillingWebhookEvent | None:
        return await self._session.scalar(
            select(BillingWebhookEvent).where(
                BillingWebhookEvent.provider == provider,
                BillingWebhookEvent.provider_event_id == provider_event_id,
            )
        )

    async def get_event(
        self, event_id: UUID, *, lock: bool = False
    ) -> BillingWebhookEvent | None:
        statement: Select[tuple[BillingWebhookEvent]] = select(
            BillingWebhookEvent
        ).where(BillingWebhookEvent.id == event_id)
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    def add_event(self, event: BillingWebhookEvent) -> None:
        self._session.add(event)

    async def claim_event_for_enqueue(self, event_id: UUID) -> bool:
        result = cast(
            CursorResult[object],
            await self._session.execute(
                update(BillingWebhookEvent)
                .where(
                    BillingWebhookEvent.id == event_id,
                    BillingWebhookEvent.status.in_(("received", "failed")),
                )
                .values(status="queued", last_error=None)
            ),
        )
        return bool(result.rowcount)

    async def release_event_enqueue(self, event_id: UUID) -> None:
        await self._session.execute(
            update(BillingWebhookEvent)
            .where(
                BillingWebhookEvent.id == event_id,
                BillingWebhookEvent.status == "queued",
            )
            .values(status="received", last_error="queue_unavailable")
        )

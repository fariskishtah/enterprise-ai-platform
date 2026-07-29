"""Persistence boundaries for tenant payments and provider callbacks."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import (
    BillingAuditEvent,
    BillingPlan,
    BillingWebhookEvent,
    InvoiceReference,
    Payment,
    Subscription,
)
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
        return cast(Payment | None, await self._session.scalar(statement))

    async def get_company_payment(
        self, payment_id: UUID, company_id: UUID, *, lock: bool = False
    ) -> Payment | None:
        statement: Select[tuple[Payment]] = select(Payment).where(
            Payment.id == payment_id,
            Payment.company_id == company_id,
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Payment | None, await self._session.scalar(statement))

    async def get_by_idempotency(
        self, company_id: UUID, idempotency_key: str
    ) -> Payment | None:
        return cast(
            Payment | None,
            await self._session.scalar(
                select(Payment).where(
                Payment.company_id == company_id,
                Payment.idempotency_key == idempotency_key,
                )
            ),
        )

    async def get_plan(self, code: str) -> BillingPlan | None:
        return cast(
            BillingPlan | None,
            await self._session.scalar(
                select(BillingPlan).where(
                    BillingPlan.code == code, BillingPlan.is_active
                )
            ),
        )

    async def get_plan_by_id(self, plan_id: UUID) -> BillingPlan | None:
        return await self._session.get(BillingPlan, plan_id)

    async def get_company_subscription(
        self, company_id: UUID, *, lock: bool = False
    ) -> Subscription | None:
        statement: Select[tuple[Subscription]] = select(Subscription).where(
            Subscription.company_id == company_id
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Subscription | None, await self._session.scalar(statement))

    async def get_subscription(
        self, subscription_id: UUID, *, lock: bool = False
    ) -> Subscription | None:
        statement: Select[tuple[Subscription]] = select(Subscription).where(
            Subscription.id == subscription_id
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Subscription | None, await self._session.scalar(statement))

    def add_subscription(self, subscription: Subscription) -> None:
        self._session.add(subscription)

    def add_audit_event(self, event: BillingAuditEvent) -> None:
        self._session.add(event)

    def add_invoice_reference(self, invoice: InvoiceReference) -> None:
        self._session.add(invoice)

    async def get_invoice_for_payment(
        self, payment_id: UUID
    ) -> InvoiceReference | None:
        return cast(
            InvoiceReference | None,
            await self._session.scalar(
                select(InvoiceReference).where(
                    InvoiceReference.payment_id == payment_id
                )
            ),
        )

    async def list_company_payments(
        self, company_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Payment], int]:
        filters = (Payment.company_id == company_id,)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(Payment).where(*filters)
            )
            or 0
        )
        rows = list(
            (
                await self._session.scalars(
                    select(Payment)
                    .where(*filters)
                    .order_by(Payment.created_at.desc(), Payment.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return rows, total

    async def list_company_invoices(
        self, company_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[InvoiceReference], int]:
        filters = (InvoiceReference.company_id == company_id,)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(InvoiceReference).where(*filters)
            )
            or 0
        )
        rows = list(
            (
                await self._session.scalars(
                    select(InvoiceReference)
                    .where(*filters)
                    .order_by(
                        InvoiceReference.issued_at.desc(), InvoiceReference.id.desc()
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return rows, total

    async def list_company_audit_events(
        self, company_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[BillingAuditEvent], int]:
        filters = (BillingAuditEvent.company_id == company_id,)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(BillingAuditEvent).where(*filters)
            )
            or 0
        )
        rows = list(
            (
                await self._session.scalars(
                    select(BillingAuditEvent)
                    .where(*filters)
                    .order_by(
                        BillingAuditEvent.created_at.desc(), BillingAuditEvent.id.desc()
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return rows, total

    async def list_company_webhook_events(
        self, company_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[BillingWebhookEvent], int]:
        filters = (BillingWebhookEvent.company_id == company_id,)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(BillingWebhookEvent).where(*filters)
            )
            or 0
        )
        rows = list(
            (
                await self._session.scalars(
                    select(BillingWebhookEvent)
                    .where(*filters)
                    .order_by(
                        BillingWebhookEvent.received_at.desc(),
                        BillingWebhookEvent.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return rows, total

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
        return cast(
            BillingWebhookEvent | None,
            await self._session.scalar(
                select(BillingWebhookEvent).where(
                BillingWebhookEvent.provider == provider,
                BillingWebhookEvent.provider_event_id == provider_event_id,
                )
            ),
        )

    async def get_event(
        self, event_id: UUID, *, lock: bool = False
    ) -> BillingWebhookEvent | None:
        statement: Select[tuple[BillingWebhookEvent]] = select(
            BillingWebhookEvent
        ).where(BillingWebhookEvent.id == event_id)
        if lock:
            statement = statement.with_for_update()
        return cast(
            BillingWebhookEvent | None, await self._session.scalar(statement)
        )

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

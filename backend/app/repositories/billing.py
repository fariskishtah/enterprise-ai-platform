"""Persistence boundaries for tenant payments and provider callbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import (
    BillingAuditEvent,
    BillingPlan,
    BillingReconciliationResult,
    BillingReconciliationRun,
    BillingWebhookEvent,
    InvoiceReference,
    Payment,
    Subscription,
)
from app.models.manufacturing import Company


class BillingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def company_is_billable(
        self,
        company_id: UUID,
        *,
        platform_scope: bool = False,
        lock: bool = False,
    ) -> bool:
        statement = select(Company.id).where(
            Company.id == company_id, Company.deleted_at.is_(None)
        )
        if platform_scope:
            statement = statement.execution_options(skip_tenant_scope=True)
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement) is not None

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

    async def get_company_payment_by_return_hash(
        self, company_id: UUID, reference_hash: str
    ) -> Payment | None:
        return cast(
            Payment | None,
            await self._session.scalar(
                select(Payment).where(
                    Payment.company_id == company_id,
                    Payment.return_reference_hash == reference_hash,
                    Payment.return_reference_purpose == "checkout_return",
                )
            ),
        )

    async def list_unresolved_company_payments(
        self, company_id: UUID, *, lock: bool = False
    ) -> list[Payment]:
        statement: Select[tuple[Payment]] = (
            select(Payment)
            .where(
                Payment.company_id == company_id,
                Payment.status.in_(("creating", "pending", "provider_error")),
            )
            .order_by(Payment.created_at, Payment.id)
        )
        if lock:
            statement = statement.with_for_update()
        return list((await self._session.scalars(statement)).all())

    async def get_plan(self, code: str) -> BillingPlan | None:
        return cast(
            BillingPlan | None,
            await self._session.scalar(
                select(BillingPlan).where(
                    BillingPlan.code == code, BillingPlan.is_active
                )
            ),
        )

    async def get_plan_record(self, code: str) -> BillingPlan | None:
        return cast(
            BillingPlan | None,
            await self._session.scalar(
                select(BillingPlan).where(BillingPlan.code == code)
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

    async def list_lifecycle_subscriptions(
        self,
        *,
        now: datetime,
        incomplete_before: datetime,
        suspended_before: datetime,
        limit: int,
    ) -> list[Subscription]:
        """Lock one bounded nonterminal lifecycle batch across worker replicas."""
        return list(
            (
                await self._session.scalars(
                    select(Subscription)
                    .where(
                        or_(
                            and_(
                                Subscription.status.in_(
                                    ("trialing", "active", "past_due")
                                ),
                                Subscription.ended_at.is_not(None),
                                Subscription.ended_at <= now,
                            ),
                            and_(
                                Subscription.status.in_(
                                    ("trialing", "active", "past_due")
                                ),
                                Subscription.suspended_at.is_not(None),
                                Subscription.suspended_at <= now,
                            ),
                            and_(
                                Subscription.status.in_(
                                    ("trialing", "active", "past_due")
                                ),
                                Subscription.cancel_at_period_end.is_(True),
                                Subscription.current_period_end.is_not(None),
                                Subscription.current_period_end <= now,
                            ),
                            and_(
                                Subscription.status == "incomplete",
                                Subscription.status_changed_at <= incomplete_before,
                            ),
                            and_(
                                Subscription.status == "past_due",
                                or_(
                                    Subscription.grace_period_ends_at.is_(None),
                                    Subscription.grace_period_ends_at <= now,
                                ),
                            ),
                            and_(
                                Subscription.status.in_(("trialing", "active")),
                                or_(
                                    Subscription.current_period_end.is_(None),
                                    Subscription.current_period_end <= now,
                                ),
                            ),
                            and_(
                                Subscription.status == "suspended",
                                Subscription.suspended_at.is_not(None),
                                Subscription.suspended_at <= suspended_before,
                            ),
                        )
                    )
                    .order_by(Subscription.status_changed_at, Subscription.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )

    async def transition_subscription_if_current(
        self,
        *,
        subscription: Subscription,
        target: str,
        now: datetime,
        suspended_at: datetime | None,
        ended_at: datetime | None,
    ) -> bool:
        """Apply one deterministic transition once even without effective row locks."""
        result = cast(
            CursorResult[object],
            await self._session.execute(
                update(Subscription)
                .where(
                    Subscription.id == subscription.id,
                    Subscription.version == subscription.version,
                    Subscription.status == subscription.status,
                )
                .values(
                    status=target,
                    status_changed_at=now,
                    suspended_at=suspended_at,
                    ended_at=ended_at,
                    cancel_at_period_end=(
                        False
                        if target in {"cancelled", "expired"}
                        else subscription.cancel_at_period_end
                    ),
                    version=Subscription.version + 1,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        return bool(result.rowcount)

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

    async def list_platform_provider_payments(
        self, provider: str, environment: str, *, limit: int
    ) -> list[Payment]:
        return list(
            (
                await self._session.scalars(
                    select(Payment)
                    .where(
                        Payment.provider == provider,
                        Payment.environment == environment,
                    )
                    .order_by(Payment.created_at.desc(), Payment.id.desc())
                    .limit(limit)
                    .execution_options(skip_tenant_scope=True)
                )
            ).all()
        )

    async def list_aged_reconcilable_payments(
        self,
        provider: str,
        environment: str,
        *,
        created_before: datetime,
        limit: int,
    ) -> list[Payment]:
        return list(
            (
                await self._session.scalars(
                    select(Payment)
                    .where(
                        Payment.provider == provider,
                        Payment.environment == environment,
                        Payment.status.in_(("creating", "pending", "provider_error")),
                        Payment.created_at <= created_before,
                    )
                    .order_by(Payment.created_at, Payment.id)
                    .limit(limit)
                    .execution_options(skip_tenant_scope=True)
                )
            ).all()
        )

    async def get_reconciliation_run(
        self, provider: str, environment: str, idempotency_key: str
    ) -> BillingReconciliationRun | None:
        return cast(
            BillingReconciliationRun | None,
            await self._session.scalar(
                select(BillingReconciliationRun)
                .where(
                    BillingReconciliationRun.provider == provider,
                    BillingReconciliationRun.environment == environment,
                    BillingReconciliationRun.idempotency_key == idempotency_key,
                )
                .execution_options(skip_tenant_scope=True)
            ),
        )

    def add_reconciliation_run(self, run: BillingReconciliationRun) -> None:
        self._session.add(run)

    def add_reconciliation_result(self, result: BillingReconciliationResult) -> None:
        self._session.add(result)

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
        return cast(BillingWebhookEvent | None, await self._session.scalar(statement))

    async def get_company_event(
        self, event_id: UUID, company_id: UUID, *, lock: bool = False
    ) -> BillingWebhookEvent | None:
        statement: Select[tuple[BillingWebhookEvent]] = select(
            BillingWebhookEvent
        ).where(
            BillingWebhookEvent.id == event_id,
            BillingWebhookEvent.company_id == company_id,
        )
        if lock:
            statement = statement.with_for_update()
        return cast(BillingWebhookEvent | None, await self._session.scalar(statement))

    def add_event(self, event: BillingWebhookEvent) -> None:
        self._session.add(event)

    async def claim_event_for_enqueue(self, event_id: UUID) -> bool:
        now = datetime.now(UTC)
        result = cast(
            CursorResult[object],
            await self._session.execute(
                update(BillingWebhookEvent)
                .where(
                    BillingWebhookEvent.id == event_id,
                    BillingWebhookEvent.company_id.is_not(None),
                    BillingWebhookEvent.validation_outcome == "accepted",
                    or_(
                        BillingWebhookEvent.status == "received",
                        and_(
                            BillingWebhookEvent.status == "failed",
                            or_(
                                BillingWebhookEvent.next_retry_at.is_(None),
                                BillingWebhookEvent.next_retry_at <= now,
                            ),
                        ),
                    ),
                )
                .values(
                    status="queued",
                    queued_at=now,
                    processing_started_at=None,
                    next_retry_at=None,
                    last_error=None,
                    last_error_category=None,
                )
            ),
        )
        return bool(result.rowcount)

    async def claim_event_for_processing(
        self, event_id: UUID, *, now: datetime
    ) -> bool:
        await self._session.execute(
            update(BillingWebhookEvent)
            .where(
                BillingWebhookEvent.id == event_id,
                BillingWebhookEvent.status == "queued",
                or_(
                    BillingWebhookEvent.company_id.is_(None),
                    BillingWebhookEvent.validation_outcome != "accepted",
                ),
            )
            .values(
                status="quarantined",
                processing_started_at=None,
                next_retry_at=None,
                processed_at=now,
                last_error="validation_not_accepted",
                last_error_category="validation_not_accepted",
            )
        )
        result = cast(
            CursorResult[object],
            await self._session.execute(
                update(BillingWebhookEvent)
                .where(
                    BillingWebhookEvent.id == event_id,
                    BillingWebhookEvent.status == "queued",
                    BillingWebhookEvent.company_id.is_not(None),
                    BillingWebhookEvent.validation_outcome == "accepted",
                )
                .values(
                    status="processing",
                    attempts=BillingWebhookEvent.attempts + 1,
                    processing_started_at=now,
                    next_retry_at=None,
                    last_error=None,
                    last_error_category=None,
                )
            ),
        )
        return bool(result.rowcount)

    async def queue_event_for_replay(
        self,
        event_id: UUID,
        company_id: UUID,
        *,
        previous_status: str,
        previous_error_category: str | None,
        replay_count: int,
        now: datetime,
    ) -> bool:
        """Atomically queue one already-validated recoverable provider event."""
        result = cast(
            CursorResult[object],
            await self._session.execute(
                update(BillingWebhookEvent)
                .where(
                    BillingWebhookEvent.id == event_id,
                    BillingWebhookEvent.company_id == company_id,
                    BillingWebhookEvent.validation_outcome == "accepted",
                    BillingWebhookEvent.status == previous_status,
                    BillingWebhookEvent.last_error_category == previous_error_category,
                    BillingWebhookEvent.replay_count == replay_count,
                )
                .values(
                    status="queued",
                    queued_at=now,
                    processing_started_at=None,
                    next_retry_at=None,
                    last_error=None,
                    last_error_category=None,
                    replay_count=BillingWebhookEvent.replay_count + 1,
                )
            ),
        )
        return bool(result.rowcount)

    async def list_recoverable_events(
        self,
        *,
        now: datetime,
        queued_before: datetime,
        processing_before: datetime,
        limit: int,
    ) -> list[BillingWebhookEvent]:
        return list(
            (
                await self._session.scalars(
                    select(BillingWebhookEvent)
                    .where(
                        BillingWebhookEvent.company_id.is_not(None),
                        BillingWebhookEvent.validation_outcome == "accepted",
                        or_(
                            BillingWebhookEvent.status == "received",
                            and_(
                                BillingWebhookEvent.status == "failed",
                                or_(
                                    BillingWebhookEvent.next_retry_at.is_(None),
                                    BillingWebhookEvent.next_retry_at <= now,
                                ),
                            ),
                            and_(
                                BillingWebhookEvent.status == "queued",
                                or_(
                                    BillingWebhookEvent.queued_at.is_(None),
                                    BillingWebhookEvent.queued_at <= queued_before,
                                ),
                            ),
                            and_(
                                BillingWebhookEvent.status == "processing",
                                or_(
                                    BillingWebhookEvent.processing_started_at.is_(None),
                                    BillingWebhookEvent.processing_started_at
                                    <= processing_before,
                                ),
                            ),
                        ),
                    )
                    .order_by(BillingWebhookEvent.received_at, BillingWebhookEvent.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )

    async def webhook_operational_stats(
        self, *, now: datetime
    ) -> tuple[int, float, float, int, int]:
        status_rows = (
            await self._session.execute(
                select(BillingWebhookEvent.status, func.count())
                .where(
                    BillingWebhookEvent.status.in_(
                        ("queued", "processing", "failed", "dead_letter")
                    )
                )
                .group_by(BillingWebhookEvent.status)
            )
        ).all()
        statuses: dict[str, int] = {status: int(count) for status, count in status_rows}
        oldest_queued = await self._session.scalar(
            select(func.min(BillingWebhookEvent.queued_at)).where(
                BillingWebhookEvent.status == "queued"
            )
        )
        oldest_processing = await self._session.scalar(
            select(func.min(BillingWebhookEvent.processing_started_at)).where(
                BillingWebhookEvent.status == "processing"
            )
        )

        def age(value: datetime | None) -> float:
            if value is None:
                return 0.0
            safe = value.replace(tzinfo=UTC) if value.tzinfo is None else value
            return max(0.0, (now - safe).total_seconds())

        return (
            int(statuses.get("queued", 0)),
            age(oldest_queued),
            age(oldest_processing),
            int(statuses.get("failed", 0)),
            int(statuses.get("dead_letter", 0)),
        )

    async def billing_state_ages(self, *, now: datetime) -> tuple[float, float]:
        """Return global unresolved ages without tenant or payment identifiers."""
        oldest_pending = await self._session.scalar(
            select(func.min(Payment.created_at))
            .where(Payment.status.in_(("creating", "pending", "provider_error")))
            .execution_options(skip_tenant_scope=True)
        )
        oldest_incomplete = await self._session.scalar(
            select(func.min(Subscription.status_changed_at))
            .where(Subscription.status == "incomplete")
            .execution_options(skip_tenant_scope=True)
        )

        def age(value: datetime | None) -> float:
            if value is None:
                return 0.0
            safe = value.replace(tzinfo=UTC) if value.tzinfo is None else value
            return max(0.0, (now - safe).total_seconds())

        return age(oldest_pending), age(oldest_incomplete)

    async def release_event_enqueue(
        self,
        event_id: UUID,
        *,
        category: str,
        message: str,
        next_retry_at: datetime,
    ) -> None:
        await self._session.execute(
            update(BillingWebhookEvent)
            .where(
                BillingWebhookEvent.id == event_id,
                BillingWebhookEvent.status == "queued",
            )
            .values(
                status="failed",
                processing_started_at=None,
                next_retry_at=next_retry_at,
                last_error_category=category[:64],
                last_error=message[:500],
            )
        )

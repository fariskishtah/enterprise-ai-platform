"""Durable transactional email persistence and worker lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from time import perf_counter
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.email import (
    EmailDeliveryStatus,
    EmailMessageType,
    OutboundEmailMessage,
)
from app.models.support import SupportRequest, SupportRequestStatus
from app.observability.logging import emit_safe
from app.observability.metrics import record_email_delivery
from app.services.email import (
    EmailDeliveryError,
    EmailProvider,
    OutboundEmail,
)
from app.utils.security import utc_now

logger = logging.getLogger(__name__)


class EmailWorkerState(StrEnum):
    SENT = "sent"
    CAPTURED = "captured"
    RETRY = "retry"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class EnqueuedEmail:
    message: OutboundEmailMessage
    created: bool


async def persist_email(
    session: AsyncSession,
    *,
    company_id: UUID | None,
    message_type: EmailMessageType,
    email: OutboundEmail,
    provider: str,
    max_retries: int,
    deduplication_key: str,
    related_resource_type: str | None = None,
    related_resource_id: UUID | None = None,
) -> EnqueuedEmail:
    """Persist a delivery once; the unique key protects repeated business events."""
    existing = await session.scalar(
        select(OutboundEmailMessage).where(
            OutboundEmailMessage.deduplication_key == deduplication_key
        )
    )
    if existing is not None:
        return EnqueuedEmail(existing, False)
    item = OutboundEmailMessage(
        company_id=company_id,
        message_type=message_type.value,
        recipient=email.to,
        from_address=email.from_address,
        from_name=email.from_name,
        reply_to=email.reply_to,
        subject=email.subject,
        text_body=email.text,
        html_body=email.html,
        provider=provider,
        status=EmailDeliveryStatus.QUEUED.value,
        max_retries=max_retries,
        deduplication_key=deduplication_key,
        related_resource_type=related_resource_type,
        related_resource_id=related_resource_id,
    )
    session.add(item)
    await session.flush()
    return EnqueuedEmail(item, True)


async def reconcile_email_delivery(
    session: AsyncSession,
    *,
    enqueue: Callable[[UUID], object],
    stale_after_seconds: int,
    limit: int,
) -> int:
    """Republish nonterminal rows after broker loss or an interrupted worker."""
    now = utc_now()
    stale_before = now - timedelta(seconds=stale_after_seconds)
    items = list(
        await session.scalars(
            select(OutboundEmailMessage)
            .where(
                or_(
                    OutboundEmailMessage.status == EmailDeliveryStatus.QUEUED.value,
                    and_(
                        OutboundEmailMessage.status
                        == EmailDeliveryStatus.RETRYING.value,
                        or_(
                            OutboundEmailMessage.next_attempt_at.is_(None),
                            OutboundEmailMessage.next_attempt_at <= now,
                        ),
                    ),
                    and_(
                        OutboundEmailMessage.status
                        == EmailDeliveryStatus.PROCESSING.value,
                        OutboundEmailMessage.updated_at <= stale_before,
                    ),
                )
            )
            .order_by(OutboundEmailMessage.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    stale_items = [
        item for item in items if item.status == EmailDeliveryStatus.PROCESSING.value
    ]
    for item in stale_items:
        item.status = EmailDeliveryStatus.QUEUED.value
        item.last_error = "stale_processing_requeued"
        item.next_attempt_at = None
    await session.commit()
    published = 0
    for item in items:
        try:
            enqueue(item.id)
        except Exception:
            break
        published += 1
    return published


class EmailDeliveryWorker:
    """Use database state as authority across at-least-once worker delivery."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        provider: EmailProvider,
        retry_base_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._retry_base_seconds = retry_base_seconds

    async def execute(self, message_id: UUID) -> EmailWorkerState:
        started = perf_counter()
        async with self._session_factory() as session:
            item = await session.scalar(
                select(OutboundEmailMessage)
                .where(OutboundEmailMessage.id == message_id)
                .with_for_update()
            )
            if item is None or item.status in {
                EmailDeliveryStatus.PROCESSING.value,
                EmailDeliveryStatus.SENT.value,
                EmailDeliveryStatus.CAPTURED.value,
                EmailDeliveryStatus.FAILED.value,
            }:
                await session.rollback()
                return EmailWorkerState.SKIPPED
            now = utc_now()
            if item.next_attempt_at is not None and item.next_attempt_at > now:
                await session.rollback()
                return EmailWorkerState.SKIPPED
            if item.attempt_count > item.max_retries:
                item.status = EmailDeliveryStatus.FAILED.value
                item.last_error = "retry_limit_reached"
                item.failed_at = now
                await self._sync_related_support(session, item)
                await session.commit()
                self._record(item, EmailWorkerState.FAILED, started)
                return EmailWorkerState.FAILED
            item.status = EmailDeliveryStatus.PROCESSING.value
            item.attempt_count += 1
            item.last_error = None
            item.next_attempt_at = None
            await session.commit()

        email = OutboundEmail(
            to=item.recipient,
            from_address=item.from_address,
            from_name=item.from_name,
            reply_to=item.reply_to,
            subject=item.subject,
            text=item.text_body,
            html=item.html_body,
        )
        try:
            result = await self._provider.send(email)
        except EmailDeliveryError as exc:
            async with self._session_factory() as session:
                current = await session.scalar(
                    select(OutboundEmailMessage)
                    .where(OutboundEmailMessage.id == message_id)
                    .with_for_update()
                )
                if current is None:
                    return EmailWorkerState.SKIPPED
                if exc.retryable and current.retry_count < current.max_retries:
                    current.retry_count += 1
                    current.status = EmailDeliveryStatus.RETRYING.value
                    current.last_error = "temporary_provider_failure"
                    delay = self._retry_base_seconds * (2 ** (current.retry_count - 1))
                    current.next_attempt_at = utc_now() + timedelta(seconds=delay)
                    await session.commit()
                    self._record(current, EmailWorkerState.RETRY, started)
                    return EmailWorkerState.RETRY
                current.status = EmailDeliveryStatus.FAILED.value
                current.last_error = (
                    "retry_limit_reached"
                    if exc.retryable
                    else "permanent_provider_failure"
                )
                current.failed_at = utc_now()
                await self._sync_related_support(session, current)
                await session.commit()
                self._record(current, EmailWorkerState.FAILED, started)
                return EmailWorkerState.FAILED

        async with self._session_factory() as session:
            current = await session.scalar(
                select(OutboundEmailMessage)
                .where(OutboundEmailMessage.id == message_id)
                .with_for_update()
            )
            if current is None:
                return EmailWorkerState.SKIPPED
            current.provider_message_id = result.provider_message_id
            current.last_error = None
            current.next_attempt_at = None
            if result.captured:
                current.status = EmailDeliveryStatus.CAPTURED.value
                state = EmailWorkerState.CAPTURED
            else:
                current.status = EmailDeliveryStatus.SENT.value
                current.sent_at = utc_now()
                state = EmailWorkerState.SENT
            await self._sync_related_support(session, current)
            await session.commit()
            self._record(current, state, started)
            return state

    @staticmethod
    async def _sync_related_support(
        session: AsyncSession, item: OutboundEmailMessage
    ) -> None:
        if (
            item.related_resource_type != "support_request"
            or item.related_resource_id is None
        ):
            return
        support = await session.get(SupportRequest, item.related_resource_id)
        if support is None:
            return
        support.delivery_attempts = item.attempt_count
        support.last_error = item.last_error
        support.provider_message_id = item.provider_message_id
        if item.status == EmailDeliveryStatus.SENT.value:
            support.status = SupportRequestStatus.DELIVERED.value
            support.delivered_at = item.sent_at
        elif item.status == EmailDeliveryStatus.FAILED.value:
            support.status = SupportRequestStatus.DELIVERY_FAILED.value

    @staticmethod
    def _record(
        item: OutboundEmailMessage, state: EmailWorkerState, started: float
    ) -> None:
        record_email_delivery(
            message_type=item.message_type,
            provider=item.provider,
            final_status=state.value,
            duration_seconds=max(perf_counter() - started, 0.0),
        )
        emit_safe(
            logger,
            logging.INFO if state is not EmailWorkerState.FAILED else logging.ERROR,
            "transactional_email_outcome",
            extra={
                "job_name": "transactional_email",
                "message_type": item.message_type,
                "provider": item.provider,
                "lifecycle_status": state.value,
                "attempt_number": item.attempt_count,
            },
        )

"""Transactional email provider, persistence, and worker lifecycle coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from app.config.settings import Settings
from app.models.email import (
    EmailDeliveryStatus,
    EmailMessageType,
    OutboundEmailMessage,
)
from app.services.email import (
    CaptureEmailProvider,
    DisabledEmailProvider,
    EmailDeliveryError,
    EmailDeliveryResult,
    OutboundEmail,
    ResendEmailProvider,
    SMTPEmailProvider,
    configured_email_provider,
    transactional_email,
)
from app.services.email_delivery import (
    EmailDeliveryWorker,
    EmailWorkerState,
    persist_email,
    reconcile_email_delivery,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def base_settings(**overrides: object) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        redis_url="redis://localhost:6379/0",
        secret_key="transactional-email-test-key-with-entropy",
        environment="test",
        **overrides,
    )


def sample_email(*, secret: str = "safe body") -> OutboundEmail:
    return OutboundEmail(
        to="recipient@example.test",
        from_address="sender@example.test",
        from_name="FK SOLUTIONS",
        reply_to="reply@example.test",
        subject="A transactional update",
        text=secret,
        html=f"<p>{secret}</p>",
    )


@dataclass
class ScriptedProvider:
    errors: list[EmailDeliveryError] = field(default_factory=list)
    messages: list[OutboundEmail] = field(default_factory=list)

    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        self.messages.append(message)
        if self.errors:
            raise self.errors.pop(0)
        return EmailDeliveryResult(provider_message_id=f"provider-{len(self.messages)}")


@pytest.mark.anyio
async def test_capture_provider_records_without_claiming_external_delivery() -> None:
    provider = CaptureEmailProvider()
    result = await provider.send(sample_email())
    assert result.captured is True
    assert result.provider_message_id.startswith("capture-")
    assert provider.messages == [sample_email()]


def test_provider_selection_and_invalid_configuration() -> None:
    assert isinstance(configured_email_provider(base_settings()), DisabledEmailProvider)
    assert isinstance(
        configured_email_provider(
            base_settings(email_provider="capture", email_from="sender@example.com")
        ),
        CaptureEmailProvider,
    )
    assert isinstance(
        configured_email_provider(
            base_settings(
                email_provider="resend",
                email_from="sender@example.com",
                resend_api_key="server-secret",
            )
        ),
        ResendEmailProvider,
    )
    assert isinstance(
        configured_email_provider(
            base_settings(
                email_provider="smtp",
                email_from="sender@example.com",
                smtp_host="smtp.example.test",
            )
        ),
        SMTPEmailProvider,
    )
    with pytest.raises(ValidationError, match="resend_api_key"):
        base_settings(
            email_provider="resend",
            email_from="sender@example.com",
            resend_api_key=None,
        )
    with pytest.raises(ValidationError, match="smtp_host"):
        base_settings(
            email_provider="smtp", email_from="sender@example.com", smtp_host=None
        )
    with pytest.raises(ValidationError, match="email_provider"):
        base_settings(email_provider="unknown")


def test_all_transactional_template_types_have_html_and_text_fallbacks() -> None:
    for message_type in EmailMessageType:
        rendered = transactional_email(
            message_type,
            recipient="recipient@example.test",
            from_address="sender@example.test",
            from_name="FK SOLUTIONS",
            reply_to=None,
            intro="Use <care> with this message.",
            action_label="Continue",
            action_url="https://platform.example/action?token=opaque",
        )
        assert rendered.subject
        assert "FK SOLUTIONS" in rendered.text
        assert "&lt;care&gt;" in rendered.html
        assert "<care>" not in rendered.html


async def persisted_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    max_retries: int = 3,
    secret: str = "safe body",
) -> OutboundEmailMessage:
    async with session_factory() as session:
        result = await persist_email(
            session,
            company_id=None,
            message_type=EmailMessageType.WELCOME,
            email=sample_email(secret=secret),
            provider="capture",
            max_retries=max_retries,
            deduplication_key=f"welcome:{uuid4()}",
        )
        await session.commit()
        return result.message


@pytest.mark.anyio
async def test_email_persistence_and_duplicate_prevention(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = f"welcome:{uuid4()}"
    async with session_factory() as session:
        first = await persist_email(
            session,
            company_id=None,
            message_type=EmailMessageType.WELCOME,
            email=sample_email(),
            provider="capture",
            max_retries=3,
            deduplication_key=key,
        )
        await session.commit()
        duplicate = await persist_email(
            session,
            company_id=None,
            message_type=EmailMessageType.WELCOME,
            email=sample_email(),
            provider="capture",
            max_retries=3,
            deduplication_key=key,
        )
        assert first.created is True
        assert duplicate.created is False
        assert duplicate.message.id == first.message.id
        assert len(list(await session.scalars(select(OutboundEmailMessage)))) == 1


@pytest.mark.anyio
async def test_reconciliation_republishes_queued_message(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    item = await persisted_message(session_factory)
    published: list[object] = []
    async with session_factory() as session:
        count = await reconcile_email_delivery(
            session,
            enqueue=lambda message_id: published.append(message_id),
            stale_after_seconds=300,
            limit=100,
        )
    assert count == 1
    assert published == [item.id]


@pytest.mark.anyio
async def test_successful_and_captured_delivery_states(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sent = await persisted_message(session_factory)
    sent_state = await EmailDeliveryWorker(
        session_factory=session_factory,
        provider=ScriptedProvider(),
        retry_base_seconds=1,
    ).execute(sent.id)
    captured = await persisted_message(session_factory)
    captured_state = await EmailDeliveryWorker(
        session_factory=session_factory,
        provider=CaptureEmailProvider(),
        retry_base_seconds=1,
    ).execute(captured.id)
    async with session_factory() as session:
        sent_row = await session.get(OutboundEmailMessage, sent.id)
        captured_row = await session.get(OutboundEmailMessage, captured.id)
    assert sent_state is EmailWorkerState.SENT
    assert sent_row is not None
    assert sent_row.status == EmailDeliveryStatus.SENT.value
    assert sent_row.sent_at is not None
    assert captured_state is EmailWorkerState.CAPTURED
    assert captured_row is not None
    assert captured_row.status == EmailDeliveryStatus.CAPTURED.value
    assert captured_row.sent_at is None


@pytest.mark.anyio
async def test_retryable_failure_then_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    item = await persisted_message(session_factory)
    provider = ScriptedProvider(
        [EmailDeliveryError("secret transport detail", retryable=True)]
    )
    worker = EmailDeliveryWorker(
        session_factory=session_factory,
        provider=provider,
        retry_base_seconds=1,
    )
    assert await worker.execute(item.id) is EmailWorkerState.RETRY
    async with session_factory() as session:
        row = await session.get(OutboundEmailMessage, item.id)
        assert row is not None
        assert row.status == EmailDeliveryStatus.RETRYING.value
        assert row.retry_count == 1
        assert row.attempt_count == 1
        assert row.next_attempt_at is not None
        row.next_attempt_at = None
        await session.commit()
    assert await worker.execute(item.id) is EmailWorkerState.SENT


@pytest.mark.anyio
async def test_permanent_failure_and_retry_limit_are_terminal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    permanent = await persisted_message(session_factory)
    permanent_state = await EmailDeliveryWorker(
        session_factory=session_factory,
        provider=ScriptedProvider([EmailDeliveryError("provider secret")]),
        retry_base_seconds=1,
    ).execute(permanent.id)
    bounded = await persisted_message(session_factory, max_retries=1)
    bounded_worker = EmailDeliveryWorker(
        session_factory=session_factory,
        provider=ScriptedProvider(
            [
                EmailDeliveryError("first secret", retryable=True),
                EmailDeliveryError("second secret", retryable=True),
            ]
        ),
        retry_base_seconds=1,
    )
    assert await bounded_worker.execute(bounded.id) is EmailWorkerState.RETRY
    async with session_factory() as session:
        row = await session.get(OutboundEmailMessage, bounded.id)
        assert row is not None
        row.next_attempt_at = None
        await session.commit()
    assert await bounded_worker.execute(bounded.id) is EmailWorkerState.FAILED
    async with session_factory() as session:
        permanent_row = await session.get(OutboundEmailMessage, permanent.id)
        bounded_row = await session.get(OutboundEmailMessage, bounded.id)
    assert permanent_state is EmailWorkerState.FAILED
    assert permanent_row is not None
    assert permanent_row.last_error == "permanent_provider_failure"
    assert bounded_row is not None
    assert bounded_row.retry_count == 1
    assert bounded_row.attempt_count == 2
    assert bounded_row.last_error == "retry_limit_reached"
    assert bounded_row.failed_at is not None


@pytest.mark.anyio
async def test_delivery_logs_do_not_contain_recipient_body_or_provider_error(
    session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    secret = "TOP-SECRET-BODY-VALUE"
    item = await persisted_message(session_factory, secret=secret)
    with caplog.at_level("INFO"):
        await EmailDeliveryWorker(
            session_factory=session_factory,
            provider=ScriptedProvider([EmailDeliveryError("PRIVATE-PROVIDER-ERROR")]),
            retry_base_seconds=1,
        ).execute(item.id)
    logs = caplog.text
    assert secret not in logs
    assert "recipient@example.test" not in logs
    assert "PRIVATE-PROVIDER-ERROR" not in logs

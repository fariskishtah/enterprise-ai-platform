"""Production subscription lifecycle transition coverage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.dependencies.billing import get_billing_webhook_queue, get_payment_provider
from app.models.billing import BillingAuditEvent
from app.models.user import UserRole
from app.repositories.billing import BillingRepository
from app.services.billing import BillingPolicy, BillingService, BillingWebhookProcessor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers
from tests.test_billing_provider_lifecycle import (
    FixtureProvider,
    RecordingBillingQueue,
    _actor,
    _billing_details,
    _event,
    _ingest_and_process,
)


@pytest.mark.anyio
async def test_initial_subscription_requires_verified_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="subscription-initial-0001",
        )
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        payment = await BillingRepository(session).get_payment(checkout.payment_id)
        assert subscription is not None and payment is not None
        assert subscription.status == "incomplete"
        assert subscription.current_period_end is None
        provider.webhooks["initial-failed"] = _event(
            payment, fixture="initial-failed", state="failed"
        )
        provider.webhooks["initial-success"] = _event(
            payment, fixture="initial-success", state="succeeded"
        )

    await _ingest_and_process(session_factory, provider, "initial-failed")
    async with session_factory() as session:
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        assert subscription is not None
        assert subscription.status == "incomplete"
        assert subscription.latest_payment_id is None

    await _ingest_and_process(session_factory, provider, "initial-success")
    async with session_factory() as session:
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        assert subscription is not None
        assert subscription.status == "active"
        assert subscription.latest_payment_id == checkout.payment_id
        assert subscription.current_period_start is not None
        assert subscription.current_period_end is not None
        assert subscription.current_period_end > subscription.current_period_start


@pytest.mark.anyio
async def test_renewal_failure_enters_grace_then_suspends(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        first = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="subscription-renewal-first",
        )
        payment = await BillingRepository(session).get_payment(first.payment_id)
        assert payment is not None
        provider.webhooks["first-success"] = _event(
            payment, fixture="first-success", state="succeeded"
        )
    await _ingest_and_process(session_factory, provider, "first-success")

    async with session_factory() as session:
        renewal = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="subscription-renewal-second",
        )
        payment = await BillingRepository(session).get_payment(renewal.payment_id)
        assert payment is not None and payment.purpose == "renewal"
        provider.webhooks["renewal-failed"] = _event(
            payment, fixture="renewal-failed", state="failed"
        )
    await _ingest_and_process(session_factory, provider, "renewal-failed")

    async with session_factory() as session:
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        assert subscription is not None
        assert subscription.status == "past_due"
        assert subscription.grace_period_ends_at is not None
        subscription.grace_period_ends_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        reconciled = await BillingService(
            session,
            None,
            policy=BillingPolicy(grace_period_days=7),
        ).reconcile_subscription(actor=actor)
        assert reconciled.status == "suspended"
        assert reconciled.suspended_at is not None


@pytest.mark.anyio
async def test_paid_upgrade_and_downgrade_apply_only_after_callback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        first = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="subscription-change-first",
        )
        payment = await BillingRepository(session).get_payment(first.payment_id)
        assert payment is not None
        provider.webhooks["change-first"] = _event(
            payment, fixture="change-first", state="succeeded"
        )
    await _ingest_and_process(session_factory, provider, "change-first")

    async with session_factory() as session:
        upgrade = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="professional",
            billing_details=_billing_details(),
            idempotency_key="subscription-upgrade-0001",
            expected_change="upgrade",
        )
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        payment = await BillingRepository(session).get_payment(upgrade.payment_id)
        assert subscription is not None and payment is not None
        current = await BillingRepository(session).get_plan_by_id(subscription.plan_id)
        assert subscription.pending_plan_id is not None
        pending = await BillingRepository(session).get_plan_by_id(
            subscription.pending_plan_id
        )
        assert current is not None and current.code == "starter"
        assert pending is not None and pending.code == "professional"
        provider.webhooks["upgrade-success"] = _event(
            payment, fixture="upgrade-success", state="succeeded"
        )
    await _ingest_and_process(session_factory, provider, "upgrade-success")

    async with session_factory() as session:
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        assert subscription is not None and subscription.pending_plan_id is None
        current = await BillingRepository(session).get_plan_by_id(subscription.plan_id)
        assert current is not None and current.code == "professional"
        downgrade = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="subscription-downgrade-0001",
            expected_change="downgrade",
        )
        payment = await BillingRepository(session).get_payment(downgrade.payment_id)
        assert payment is not None
        provider.webhooks["downgrade-success"] = _event(
            payment, fixture="downgrade-success", state="succeeded"
        )
    await _ingest_and_process(session_factory, provider, "downgrade-success")
    async with session_factory() as session:
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        assert subscription is not None
        current = await BillingRepository(session).get_plan_by_id(subscription.plan_id)
        assert current is not None and current.code == "starter"


@pytest.mark.anyio
async def test_cancellation_reactivation_and_immediate_cancel_are_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        first = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="subscription-cancel-first",
        )
        payment = await BillingRepository(session).get_payment(first.payment_id)
        assert payment is not None
        provider.webhooks["cancel-first"] = _event(
            payment, fixture="cancel-first", state="succeeded"
        )
    await _ingest_and_process(session_factory, provider, "cancel-first")

    async with session_factory() as session:
        service = BillingService(session, None)
        scheduled = await service.cancel_subscription(actor=actor)
        assert scheduled.status == "active"
        assert scheduled.cancel_at_period_end is True
        reactivated = await service.reactivate_subscription(actor=actor)
        assert reactivated.cancel_at_period_end is False
        cancelled = await service.cancel_subscription(actor=actor, immediate=True)
        assert cancelled.status == "cancelled"
        events = list(
            (
                await session.scalars(
                    select(BillingAuditEvent).where(
                        BillingAuditEvent.company_id == actor.company_id
                    )
                )
            ).all()
        )
        actions = {event.action for event in events}
        assert "subscription.cancellation_scheduled" in actions
        assert "subscription.reactivated" in actions
        assert "subscription.cancelled_immediately" in actions


@pytest.mark.anyio
@pytest.mark.parametrize("terminal_state", ["refunded", "reversed"])
async def test_terminal_payment_event_suspends_and_late_success_cannot_reactivate(
    session_factory: async_sessionmaker[AsyncSession], terminal_state: str
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key=f"subscription-terminal-{terminal_state}",
        )
        payment = await BillingRepository(session).get_payment(checkout.payment_id)
        assert payment is not None
        provider.webhooks["terminal-success"] = _event(
            payment, fixture="terminal-success", state="succeeded"
        )
        provider.webhooks[terminal_state] = _event(
            payment, fixture=terminal_state, state=terminal_state
        )
        provider.webhooks["late-success"] = _event(
            payment, fixture="late-success", state="succeeded"
        )
    await _ingest_and_process(session_factory, provider, "terminal-success")
    await _ingest_and_process(session_factory, provider, terminal_state)
    await _ingest_and_process(session_factory, provider, "late-success")

    async with session_factory() as session:
        subscription = await BillingRepository(session).get_company_subscription(
            actor.company_id
        )
        assert subscription is not None
        assert subscription.status == "suspended"
        assert subscription.latest_payment_id == checkout.payment_id


@pytest.mark.anyio
async def test_subscription_history_and_admin_api_contracts(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    provider = FixtureProvider()
    queue = RecordingBillingQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_payment_provider] = lambda: provider
        application.dependency_overrides[get_billing_webhook_queue] = lambda: queue
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="subscription-api-owner@example.com",
        )
        created = await client.post(
            "/billing/checkouts",
            headers={**headers, "Idempotency-Key": "subscription-api-checkout"},
            json={
                "plan_code": "starter",
                "billing_details": {
                    "first_name": "Factory",
                    "last_name": "Owner",
                    "phone_number": "+201001234567",
                    "city": "Cairo",
                    "country": "EG",
                    "street": "Industrial Zone",
                },
            },
        )
        assert created.status_code == 201, created.text
        payment_id = UUID(created.json()["payment_id"])
        async with session_factory() as session:
            payment = await BillingRepository(session).get_payment(payment_id)
            assert payment is not None
            provider.webhooks["api-lifecycle-success"] = _event(
                payment, fixture="api-lifecycle-success", state="succeeded"
            )
        callback = await client.post(
            "/billing/webhooks/paymob?hmac=fixture",
            json={"fixture": "api-lifecycle-success"},
        )
        assert callback.status_code == 202
        await BillingWebhookProcessor(session_factory, "paymob").execute(
            queue.event_ids[-1]
        )

        current = await client.get("/billing/subscription", headers=headers)
        payments = await client.get("/billing/history/payments", headers=headers)
        invoices = await client.get("/billing/history/invoices", headers=headers)
        events = await client.get("/billing/admin/events", headers=headers)
        provider_events = await client.get(
            "/billing/admin/provider-events", headers=headers
        )
        scheduled = await client.post(
            "/billing/subscription/cancel",
            headers=headers,
            json={"mode": "period_end"},
        )
        reactivated = await client.post(
            "/billing/subscription/reactivate", headers=headers
        )

        assert current.status_code == 200
        assert current.json()["item"]["status"] == "active"
        assert payments.status_code == 200 and payments.json()["total"] == 1
        assert invoices.status_code == 200 and invoices.json()["total"] == 1
        assert events.status_code == 200 and events.json()["total"] >= 3
        assert provider_events.status_code == 200
        assert provider_events.json()["total"] == 1
        assert scheduled.status_code == 200
        assert scheduled.json()["cancel_at_period_end"] is True
        assert reactivated.status_code == 200
        assert reactivated.json()["cancel_at_period_end"] is False

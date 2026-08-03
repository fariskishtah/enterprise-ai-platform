"""Critical billing Phase 1 security, lifecycle, and recovery invariants."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.config.settings import Settings
from app.dependencies.billing import get_billing_webhook_queue
from app.models.billing import (
    BillingAuditEvent,
    BillingWebhookEvent,
    Payment,
    Subscription,
)
from app.models.manufacturing import Company
from app.models.user import User, UserRole
from app.services.billing import (
    BillingPolicy,
    BillingService,
    BillingWebhookProcessor,
    BillingWebhookRecoveryService,
    SubscriptionLifecycleReconciler,
)
from app.services.entitlements import EntitlementService, SubscriptionAccessError
from sqlalchemy import func, select
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
from tests.test_entitlements import _activate


async def _mark_platform_operator(
    session_factory: async_sessionmaker[AsyncSession], *, email: str
) -> User:
    async with session_factory() as session:
        actor = await session.scalar(select(User).where(User.email == email))
        assert actor is not None
        actor.is_platform_operator = True
        await session.commit()
        return actor


@pytest.mark.anyio
@pytest.mark.parametrize("role", list(UserRole))
async def test_every_tenant_role_is_denied_entitlement_override(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    role: UserRole,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        headers = await auth_headers(
            client,
            session_factory,
            role=role,
            email=f"override-denied-{role.value}@example.com",
        )
        async with session_factory() as session:
            actor = await session.scalar(
                select(User).where(
                    User.email == f"override-denied-{role.value}@example.com"
                )
            )
            assert actor is not None
        response = await client.put(
            f"/billing/platform/tenants/{actor.company_id}/entitlement-overrides/factories",
            headers={
                **headers,
                "X-Request-ID": f"override-denied-{role.value}",
                "X-Correlation-ID": "override-denied-matrix",
            },
            json={"integer_limit": 2, "reason": "Support-approved exception"},
        )
        assert response.status_code == 403


@pytest.mark.anyio
async def test_platform_operator_override_is_tenant_scoped_and_fully_audited(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    target_company_id = uuid4()
    queue = RecordingBillingQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_billing_webhook_queue] = lambda: queue
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.VIEWER,
            email="platform-billing-operator@example.com",
        )
        operator = await _mark_platform_operator(
            session_factory, email="platform-billing-operator@example.com"
        )
        async with session_factory() as session:
            session.add(
                Company(
                    id=target_company_id,
                    name="Override target tenant",
                    normalized_name="override target tenant",
                )
            )
            await session.commit()

        request_headers = {
            **headers,
            "X-Request-ID": "override-change-request",
            "X-Correlation-ID": "override-change-correlation",
        }
        created = await client.put(
            f"/billing/platform/tenants/{target_company_id}/entitlement-overrides/factories",
            headers=request_headers,
            json={"integer_limit": 3, "reason": "Support ticket BILL-42"},
        )
        updated = await client.put(
            f"/billing/platform/tenants/{target_company_id}/entitlement-overrides/factories",
            headers=request_headers,
            json={"integer_limit": 4, "reason": "Support ticket BILL-43"},
        )
        missing_delete_reason = await client.request(
            "DELETE",
            f"/billing/platform/tenants/{target_company_id}/entitlement-overrides/factories",
            headers=request_headers,
            json={},
        )
        deleted = await client.request(
            "DELETE",
            f"/billing/platform/tenants/{target_company_id}/entitlement-overrides/factories",
            headers=request_headers,
            json={"reason": "Support ticket BILL-44 closed"},
        )
        assert created.status_code == 200, created.text
        assert updated.status_code == 200, updated.text
        assert created.json()["integer_limit"] == 3
        assert updated.json()["integer_limit"] == 4
        assert missing_delete_reason.status_code == 422
        assert deleted.status_code == 204

    async with session_factory() as session:
        audits = list(
            (
                await session.scalars(
                    select(BillingAuditEvent)
                    .where(
                        BillingAuditEvent.company_id == target_company_id,
                        BillingAuditEvent.action == "entitlement.override_set",
                    )
                    .order_by(BillingAuditEvent.created_at, BillingAuditEvent.id)
                )
            ).all()
        )
        assert len(audits) == 2
        by_reason = {item.safe_metadata["reason"]: item for item in audits}
        created_audit = by_reason["Support ticket BILL-42"]
        updated_audit = by_reason["Support ticket BILL-43"]
        assert created_audit.actor_user_id == operator.id
        assert created_audit.safe_metadata["entitlement_key"] == "factories"
        assert created_audit.safe_metadata["previous_value"] is None
        assert created_audit.safe_metadata["new_value"] == {
            "integer_limit": 3,
            "enabled": None,
            "expires_at": None,
        }
        assert updated_audit.safe_metadata["previous_value"]["integer_limit"] == 3
        assert updated_audit.safe_metadata["new_value"]["integer_limit"] == 4
        assert updated_audit.safe_metadata["request_id"] == "override-change-request"
        assert (
            updated_audit.safe_metadata["correlation_id"]
            == "override-change-correlation"
        )
        deleted_audit = await session.scalar(
            select(BillingAuditEvent).where(
                BillingAuditEvent.company_id == target_company_id,
                BillingAuditEvent.action == "entitlement.override_deleted",
            )
        )
        assert deleted_audit is not None
        assert deleted_audit.safe_metadata["previous_value"]["integer_limit"] == 4
        assert deleted_audit.safe_metadata["new_value"] is None
        assert deleted_audit.safe_metadata["reason"] == "Support ticket BILL-44 closed"
        own_tenant_audits = await session.scalar(
            select(func.count())
            .select_from(BillingAuditEvent)
            .where(
                BillingAuditEvent.company_id == operator.company_id,
                BillingAuditEvent.action.in_(
                    ("entitlement.override_set", "entitlement.override_deleted")
                ),
            )
        )
        assert own_tenant_audits == 0


@pytest.mark.anyio
async def test_platform_override_rejects_missing_reason_and_unknown_key(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="platform-validation@example.com",
        )
        actor = await _mark_platform_operator(
            session_factory, email="platform-validation@example.com"
        )
        missing_reason = await client.put(
            f"/billing/platform/tenants/{actor.company_id}/entitlement-overrides/factories",
            headers=headers,
            json={"integer_limit": 2},
        )
        invalid_key = await client.put(
            f"/billing/platform/tenants/{actor.company_id}/entitlement-overrides/not-real",
            headers=headers,
            json={"integer_limit": 2, "reason": "Support ticket BILL-44"},
        )
        assert missing_reason.status_code == 422
        assert invalid_key.status_code == 422


@pytest.mark.anyio
async def test_entitlement_access_enforces_period_and_grace_without_billing_read(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    subscription = await _activate(
        session_factory, company_id=actor.company_id, plan_code="professional"
    )
    async with session_factory() as session:
        entity = await session.get(Subscription, subscription.id)
        assert entity is not None
        entity.current_period_end = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(SubscriptionAccessError):
            await EntitlementService(session).require_feature(
                actor.company_id, "model_training"
            )

        entity.status = "past_due"
        entity.grace_period_ends_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.commit()
        await EntitlementService(session).require_feature(
            actor.company_id, "model_training"
        )

        entity.grace_period_ends_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(SubscriptionAccessError):
            await EntitlementService(session).require_feature(
                actor.company_id, "model_training"
            )


@pytest.mark.anyio
async def test_lifecycle_reconciler_is_idempotent_and_audits_one_transition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    subscription = await _activate(
        session_factory, company_id=actor.company_id, plan_code="starter"
    )
    now = datetime.now(UTC)
    async with session_factory() as session:
        entity = await session.get(Subscription, subscription.id)
        assert entity is not None
        entity.current_period_end = now - timedelta(minutes=1)
        entity.cancel_at_period_end = True
        await session.commit()

    reconciler = SubscriptionLifecycleReconciler(
        session_factory, policy=BillingPolicy()
    )
    first = await reconciler.run(now=now, limit=100)
    second = await reconciler.run(now=now, limit=100)
    assert first.scanned >= 1
    assert first.transitioned == 1
    assert first.failures == 0
    assert second.transitioned == 0

    async with session_factory() as session:
        entity = await session.get(Subscription, subscription.id)
        audit_count = await session.scalar(
            select(func.count())
            .select_from(BillingAuditEvent)
            .where(
                BillingAuditEvent.company_id == actor.company_id,
                BillingAuditEvent.action == "subscription.period_cancelled",
            )
        )
        assert entity is not None and entity.status == "cancelled"
        assert audit_count == 1


@pytest.mark.anyio
async def test_concurrent_lifecycle_reconciliation_has_one_final_transition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    subscription = await _activate(
        session_factory, company_id=actor.company_id, plan_code="starter"
    )
    now = datetime.now(UTC)
    async with session_factory() as session:
        entity = await session.get(Subscription, subscription.id)
        assert entity is not None
        entity.current_period_end = now - timedelta(seconds=1)
        await session.commit()

    results = await asyncio.gather(
        SubscriptionLifecycleReconciler(session_factory).run(now=now, limit=100),
        SubscriptionLifecycleReconciler(session_factory).run(now=now, limit=100),
    )
    assert sum(item.transitioned for item in results) == 1
    async with session_factory() as session:
        entity = await session.get(Subscription, subscription.id)
        assert entity is not None and entity.status == "expired"


def _webhook_event(
    *,
    company_id: UUID,
    status: str,
    now: datetime,
    attempts: int = 0,
) -> BillingWebhookEvent:
    return BillingWebhookEvent(
        company_id=company_id,
        provider="paymob",
        provider_event_id=f"phase1:{uuid4()}",
        event_type="transaction.succeeded",
        payload_hash=uuid4().hex * 2,
        safe_payload={},
        status=status,
        attempts=attempts,
        queued_at=now if status == "queued" else None,
        processing_started_at=now if status == "processing" else None,
    )


@pytest.mark.anyio
async def test_stale_queued_and_processing_webhooks_are_reclaimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    queue = RecordingBillingQueue()
    now = datetime.now(UTC)
    async with session_factory() as session:
        queued = _webhook_event(
            company_id=actor.company_id,
            status="queued",
            now=now - timedelta(minutes=10),
        )
        processing = _webhook_event(
            company_id=actor.company_id,
            status="processing",
            now=now - timedelta(minutes=10),
            attempts=1,
        )
        session.add_all([queued, processing])
        await session.commit()

    summary = await BillingWebhookRecoveryService(
        session_factory,
        queue,
        max_attempts=5,
        retry_base_seconds=1,
        queued_stale_seconds=60,
        processing_stale_seconds=60,
    ).run(now=now, limit=100)
    assert set(queue.event_ids) == {queued.id, processing.id}
    assert summary.requeued == 2
    assert summary.queue_depth >= 2


@pytest.mark.anyio
async def test_stale_processing_at_retry_limit_enters_dead_letter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    queue = RecordingBillingQueue()
    now = datetime.now(UTC)
    async with session_factory() as session:
        event = _webhook_event(
            company_id=actor.company_id,
            status="processing",
            now=now - timedelta(minutes=10),
            attempts=3,
        )
        session.add(event)
        await session.commit()

    summary = await BillingWebhookRecoveryService(
        session_factory,
        queue,
        max_attempts=3,
        retry_base_seconds=1,
        queued_stale_seconds=60,
        processing_stale_seconds=60,
    ).run(now=now, limit=100)
    async with session_factory() as session:
        stored = await session.get(BillingWebhookEvent, event.id)
        assert stored is not None
        assert stored.status == "dead_letter"
        assert stored.dead_lettered_at is not None
        assert stored.dead_lettered_at.replace(tzinfo=UTC) == now
        assert stored.last_error_category == "worker_stale"
    assert summary.dead_lettered == 1
    assert queue.event_ids == []


@pytest.mark.anyio
async def test_processing_failures_back_off_then_exhaust_to_dead_letter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    queue = RecordingBillingQueue()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="phase1-retry-exhaustion",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks["phase1-retry-failure"] = _event(
            payment, fixture="phase1-retry-failure", state="succeeded"
        )
        payment.plan_code = "removed-plan"
        await session.commit()
        ingested = await BillingService(session, provider).ingest_webhook(
            {"fixture": "phase1-retry-failure"}, signature="valid"
        )

    processor = BillingWebhookProcessor(
        session_factory, "paymob", max_attempts=2, retry_base_seconds=1
    )
    await processor.execute(ingested.event_id)
    async with session_factory() as session:
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        payment = await session.get(Payment, checkout.payment_id)
        assert event is not None and payment is not None
        assert event.status == "failed"
        assert event.attempts == 1
        assert event.next_retry_at is not None
        retry_at = event.next_retry_at.replace(tzinfo=UTC)
        assert payment.status == "pending"

    recovery = BillingWebhookRecoveryService(
        session_factory,
        queue,
        max_attempts=2,
        retry_base_seconds=1,
        queued_stale_seconds=60,
        processing_stale_seconds=60,
    )
    early = await recovery.run(now=retry_at - timedelta(milliseconds=1), limit=100)
    due = await recovery.run(now=retry_at + timedelta(milliseconds=1), limit=100)
    assert early.requeued == 0
    assert due.requeued == 1
    assert queue.event_ids == [ingested.event_id]

    await processor.execute(ingested.event_id)
    async with session_factory() as session:
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        payment = await session.get(Payment, checkout.payment_id)
        assert event is not None and payment is not None
        assert event.status == "dead_letter"
        assert event.attempts == 2
        assert event.dead_lettered_at is not None
        assert event.last_error_category == "billing_state_error"
        assert payment.status == "pending"


@pytest.mark.anyio
async def test_safe_replay_is_platform_only_tenant_scoped_and_idempotent(
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
        application.dependency_overrides[get_billing_webhook_queue] = lambda: queue
        owner_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="replay-owner@example.com",
        )
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="replay-admin@example.com",
        )
        async with session_factory() as session:
            actor = await session.scalar(
                select(User).where(User.email == "replay-owner@example.com")
            )
            assert actor is not None
            checkout = await BillingService(session, provider).create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key="phase1-safe-replay-checkout",
            )
            payment = await session.get(Payment, checkout.payment_id)
            assert payment is not None
            provider.webhooks["phase1-replay-success"] = _event(
                payment, fixture="phase1-replay-success", state="succeeded"
            )
        event_id = await _ingest_and_process(
            session_factory, provider, "phase1-replay-success"
        )
        async with session_factory() as session:
            subscription = await session.scalar(
                select(Subscription).where(Subscription.company_id == actor.company_id)
            )
            assert subscription is not None
            original_period_end = subscription.current_period_end

        denied = await client.post(
            f"/billing/platform/tenants/{actor.company_id}/provider-events/{event_id}/replay",
            headers=owner_headers,
            json={"reason": "Support ticket BILL-45"},
        )
        denied_admin = await client.post(
            f"/billing/platform/tenants/{actor.company_id}/provider-events/{event_id}/replay",
            headers=admin_headers,
            json={"reason": "Support ticket BILL-45"},
        )
        assert denied.status_code == 403
        assert denied_admin.status_code == 403

        operator = await _mark_platform_operator(
            session_factory, email="replay-owner@example.com"
        )
        wrong_tenant = await client.post(
            f"/billing/platform/tenants/{uuid4()}/provider-events/{event_id}/replay",
            headers=owner_headers,
            json={"reason": "Support ticket BILL-45"},
        )
        replay = await client.post(
            f"/billing/platform/tenants/{actor.company_id}/provider-events/{event_id}/replay",
            headers={**owner_headers, "X-Request-ID": "safe-replay-request"},
            json={"reason": "Support ticket BILL-45"},
        )
        assert wrong_tenant.status_code == 404
        assert replay.status_code == 200, replay.text
        assert replay.json()["replay_count"] == 1
        assert queue.event_ids == [event_id]

        await BillingWebhookProcessor(session_factory, "paymob").execute(event_id)
        async with session_factory() as session:
            subscription = await session.scalar(
                select(Subscription).where(Subscription.company_id == actor.company_id)
            )
            event = await session.get(BillingWebhookEvent, event_id)
            audit = await session.scalar(
                select(BillingAuditEvent).where(
                    BillingAuditEvent.company_id == actor.company_id,
                    BillingAuditEvent.action == "webhook.safe_replay",
                )
            )
            assert subscription is not None and event is not None and audit is not None
            assert subscription.current_period_end == original_period_end
            assert event.status == "processed"
            assert event.attempts == 2
            assert audit.actor_user_id == operator.id
            assert audit.safe_metadata["reason"] == "Support ticket BILL-45"

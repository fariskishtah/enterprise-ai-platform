"""Critical billing Phase 1 security, lifecycle, and recovery invariants."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
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
from app.repositories.billing import BillingRepository
from app.services.billing import (
    BillingConflictError,
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

    actor.is_platform_operator = True
    async with session_factory() as session:
        with pytest.raises(BillingConflictError, match="not eligible"):
            await BillingService(session, provider).replay_webhook_event(
                actor=actor,
                company_id=actor.company_id,
                event_id=ingested.event_id,
                reason="State errors are not operationally replayable",
            )


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
        async with session_factory() as session:
            service = BillingService(session, provider)
            ingested = await service.ingest_webhook(
                {"fixture": "phase1-replay-success"}, signature="valid"
            )
            assert ingested.should_enqueue is True
            await service.release_failed_enqueue(
                ingested.event_id, category="queue_unavailable"
            )
            event_id = ingested.event_id
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
        duplicate_replay = await client.post(
            f"/billing/platform/tenants/{actor.company_id}/provider-events/{event_id}/replay",
            headers={**owner_headers, "X-Request-ID": "duplicate-replay-request"},
            json={"reason": "Support ticket BILL-45 duplicate"},
        )
        assert duplicate_replay.status_code == 409
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
            assert original_period_end is None
            assert subscription.current_period_end is not None
            assert event.status == "processed"
            assert event.attempts == 1
            assert event.replay_count == 1
            assert audit.actor_user_id == operator.id
            assert audit.safe_metadata["reason"] == "Support ticket BILL-45"
            rejected_audit = await session.scalar(
                select(BillingAuditEvent).where(
                    BillingAuditEvent.company_id == actor.company_id,
                    BillingAuditEvent.action == "webhook.replay_rejected",
                )
            )
            assert rejected_audit is not None
            assert rejected_audit.safe_metadata["rejection_reason"] in {
                "state_not_replayable",
                "already_completed",
            }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("validation_outcome", "money_field"),
    [
        ("quarantined_wrong_integration", None),
        ("quarantined_wrong_environment", None),
        ("quarantined_wrong_merchant", None),
        ("quarantined_unsupported_semantics", None),
        ("quarantined_invalid_hmac", None),
        ("accepted", "amount"),
        ("accepted", "currency"),
    ],
)
async def test_security_rejected_callbacks_cannot_be_replayed(
    session_factory: async_sessionmaker[AsyncSession],
    validation_outcome: str,
    money_field: str | None,
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    fixture = f"replay-rejected-{validation_outcome}-{money_field}"
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key=f"{fixture}-checkout",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        callback = replace(
            _event(payment, fixture=fixture, state="succeeded"),
            validation_outcome=validation_outcome,
            integration_id=999,
            environment="sandbox",
            merchant_id="700001",
            source_type="card",
            amount_minor=(
                (payment.amount_minor + 1)
                if money_field == "amount"
                else payment.amount_minor
            ),
            currency="USD" if money_field == "currency" else payment.currency,
        )
        provider.webhooks[fixture] = callback
        ingested = await BillingService(session, provider).ingest_webhook(
            {"fixture": fixture}, signature="valid"
        )
        assert ingested.should_enqueue is False

    operator = await _mark_platform_operator(session_factory, email=actor.email)
    async with session_factory() as session:
        with pytest.raises(BillingConflictError, match="not eligible"):
            await BillingService(session, provider).replay_webhook_event(
                actor=operator,
                company_id=actor.company_id,
                event_id=ingested.event_id,
                reason="Security review rejected callback replay",
            )

    async with session_factory() as session:
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        payment = await session.get(Payment, checkout.payment_id)
        subscription = await session.scalar(
            select(Subscription).where(Subscription.company_id == actor.company_id)
        )
        audit = await session.scalar(
            select(BillingAuditEvent).where(
                BillingAuditEvent.company_id == actor.company_id,
                BillingAuditEvent.action == "webhook.replay_rejected",
            )
        )
        assert event is not None and payment is not None and subscription is not None
        assert event.status == "quarantined"
        assert event.replay_count == 0
        assert payment.status == "pending"
        assert subscription.status == "incomplete"
        assert subscription.current_period_end is None
        assert audit is not None
        assert audit.safe_metadata["replay_eligibility"] == "rejected"


@pytest.mark.anyio
async def test_missing_validation_evidence_cannot_be_replayed_or_claimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    operator = actor
    operator.is_platform_operator = True
    now = datetime.now(UTC)
    event = BillingWebhookEvent(
        company_id=actor.company_id,
        provider="paymob",
        provider_event_id=f"missing-validation:{uuid4()}",
        event_type="transaction.captured",
        payload_hash=uuid4().hex * 2,
        safe_payload={"validation_outcome": "accepted"},
        validation_outcome="quarantined_wrong_integration",
        status="failed",
        attempts=1,
        last_error="processing_error",
        last_error_category="processing_error",
    )
    async with session_factory() as session:
        session.add(event)
        await session.commit()
        with pytest.raises(BillingConflictError, match="not eligible"):
            await BillingService(session, None).replay_webhook_event(
                actor=operator,
                company_id=actor.company_id,
                event_id=event.id,
                reason="Attempt to replay missing validation evidence",
            )
        stored = await session.get(BillingWebhookEvent, event.id)
        assert stored is not None
        stored.status = "queued"
        await session.commit()
        claimed = await BillingRepository(session).claim_event_for_processing(
            event.id, now=now
        )
        await session.commit()
        await session.refresh(stored)
        assert claimed is False
        assert stored.status == "quarantined"
        assert stored.replay_count == 0
        assert stored.last_error_category == "validation_not_accepted"


@pytest.mark.anyio
async def test_replay_compare_and_set_rejects_a_concurrent_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    event = BillingWebhookEvent(
        company_id=actor.company_id,
        provider="paymob",
        provider_event_id=f"concurrent-replay:{uuid4()}",
        event_type="transaction.captured",
        payload_hash=uuid4().hex * 2,
        safe_payload={"validation_outcome": "accepted"},
        validation_outcome="accepted",
        status="dead_letter",
        attempts=5,
        last_error="Webhook processing failed.",
        last_error_category="processing_error",
    )
    async with session_factory() as session:
        session.add(event)
        await session.commit()
        repository = BillingRepository(session)
        first = await repository.queue_event_for_replay(
            event.id,
            actor.company_id,
            previous_status="dead_letter",
            previous_error_category="processing_error",
            replay_count=0,
            now=datetime.now(UTC),
        )
        stale_duplicate = await repository.queue_event_for_replay(
            event.id,
            actor.company_id,
            previous_status="dead_letter",
            previous_error_category="processing_error",
            replay_count=0,
            now=datetime.now(UTC),
        )
        await session.commit()
        await session.refresh(event)

    assert first is True
    assert stale_duplicate is False
    assert event.status == "queued"
    assert event.replay_count == 1


@pytest.mark.anyio
async def test_concurrent_replay_conflict_is_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    operator = await _mark_platform_operator(session_factory, email=actor.email)
    event = BillingWebhookEvent(
        company_id=actor.company_id,
        provider="paymob",
        provider_event_id=f"concurrent-replay-audit:{uuid4()}",
        event_type="transaction.captured",
        payload_hash=uuid4().hex * 2,
        safe_payload={"validation_outcome": "accepted"},
        validation_outcome="accepted",
        status="dead_letter",
        attempts=5,
        last_error="Webhook processing failed.",
        last_error_category="processing_error",
    )
    async with session_factory() as session:
        session.add(event)
        await session.commit()
        service = BillingService(session, None)
        service._repository.queue_event_for_replay = AsyncMock(return_value=False)
        with pytest.raises(BillingConflictError, match="changed"):
            await service.replay_webhook_event(
                actor=operator,
                company_id=actor.company_id,
                event_id=event.id,
                reason="Concurrent support replay request",
            )
        audit = await session.scalar(
            select(BillingAuditEvent).where(
                BillingAuditEvent.action == "webhook.replay_rejected"
            )
        )

    assert audit is not None
    assert audit.safe_metadata["rejection_reason"] == "concurrent_change"
    assert audit.safe_metadata["resulting_status"] == "concurrent_change"


@pytest.mark.anyio
async def test_recoverable_dead_letter_replay_activates_exactly_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    fixture = "recoverable-dead-letter-success"
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="recoverable-dead-letter-checkout",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks[fixture] = _event(payment, fixture=fixture, state="succeeded")
        ingested = await BillingService(session, provider).ingest_webhook(
            {"fixture": fixture}, signature="valid"
        )
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        assert event is not None
        event.status = "dead_letter"
        event.attempts = 5
        event.last_error = "Webhook processing failed."
        event.last_error_category = "processing_error"
        await session.commit()

    operator = await _mark_platform_operator(session_factory, email=actor.email)
    async with session_factory() as session:
        replayed = await BillingService(session, provider).replay_webhook_event(
            actor=operator,
            company_id=actor.company_id,
            event_id=ingested.event_id,
            reason="Retry exhausted transient worker failure",
        )
        assert replayed.status == "queued"
        assert replayed.replay_count == 1

    processor = BillingWebhookProcessor(session_factory, "paymob")
    await asyncio.gather(
        processor.execute(ingested.event_id),
        processor.execute(ingested.event_id),
    )
    async with session_factory() as session:
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        subscription = await session.scalar(
            select(Subscription).where(Subscription.company_id == actor.company_id)
        )
        assert event is not None and subscription is not None
        assert event.status == "processed"
        assert event.attempts == 6
        assert subscription.status == "active"
        assert subscription.latest_payment_id == checkout.payment_id
        assert subscription.current_period_end is not None


@pytest.mark.anyio
async def test_timezone_less_provider_timestamp_processes_successfully(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    fixture = "timezone-less-provider-success"
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="professional",
            billing_details=_billing_details(),
            idempotency_key="timezone-less-provider-success",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks[fixture] = _event(payment, fixture=fixture, state="succeeded")
        ingested = await BillingService(session, provider).ingest_webhook(
            {"fixture": fixture}, signature="valid"
        )
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        assert event is not None and event.safe_payload is not None
        payment.checkout_expires_at = event.received_at + timedelta(minutes=1)
        event.safe_payload = {
            **event.safe_payload,
            "occurred_at": (event.received_at + timedelta(hours=3))
            .replace(tzinfo=None)
            .isoformat(),
        }
        await session.commit()

    await BillingWebhookProcessor(session_factory, "paymob").execute(ingested.event_id)

    async with session_factory() as session:
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        payment = await session.get(Payment, checkout.payment_id)
        subscription = await session.scalar(
            select(Subscription).where(Subscription.company_id == actor.company_id)
        )
        assert event is not None and payment is not None and subscription is not None
        assert event.status == "processed"
        assert payment.status == "succeeded"
        assert payment.checkout_intent_status == "completed"
        assert subscription.status == "active"
        assert subscription.latest_payment_id == payment.id


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tampered_field", "tampered_value", "expected_reason"),
    [
        ("integration_id", 999999, "integration_mismatch"),
        ("environment", "live", "environment_mismatch"),
        ("merchant_id", "999999", "merchant_mismatch"),
        ("source_type", "wallet", "source_mismatch"),
        (
            "provider_order_id",
            "order-tampered",
            "provider_order_mismatch",
        ),
        (
            "payment_reference",
            "00000000-0000-0000-0000-000000000001",
            "payment_not_found",
        ),
        ("amount_minor", 1, "amount_mismatch"),
        ("currency", "USD", "currency_mismatch"),
        (
            "validation_outcome",
            "quarantined_wrong_integration",
            "validation_evidence_missing",
        ),
        ("event_provider", "other", "provider_tenant_mismatch"),
        ("event_company_id", "other", "tenant_mismatch"),
        (
            "event_validation_outcome",
            "quarantined_wrong_integration",
            "validation_not_accepted",
        ),
    ],
)
async def test_direct_processor_invocation_revalidates_complete_binding(
    session_factory: async_sessionmaker[AsyncSession],
    tampered_field: str,
    tampered_value: object,
    expected_reason: str,
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    policy = BillingPolicy(
        environment="sandbox",
        provider_integration_id=123456,
        provider_merchant_id="700001",
        provider_source_types=("card",),
    )
    fixture = f"processor-binding-{tampered_field}"
    async with session_factory() as session:
        checkout = await BillingService(
            session, provider, policy=policy
        ).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key=f"{fixture}-checkout",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks[fixture] = replace(
            _event(payment, fixture=fixture, state="succeeded"),
            validation_outcome="accepted",
            integration_id=123456,
            environment="sandbox",
            merchant_id="700001",
            source_type="card",
        )
        ingested = await BillingService(
            session, provider, policy=policy
        ).ingest_webhook({"fixture": fixture}, signature="valid")
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        assert event is not None and event.safe_payload is not None
        if tampered_field == "provider_order_id":
            payment.provider_order_id = "order-expected"
            event.safe_payload = {
                **event.safe_payload,
                "provider_order_id": "order-expected",
            }
        event.status = "processing"
        event.processing_started_at = datetime.now(UTC)
        if tampered_field == "event_provider":
            event.provider = str(tampered_value)
        elif tampered_field == "event_company_id":
            other_company = Company(
                id=uuid4(),
                name="Processor tenant mismatch",
                normalized_name=f"processor tenant mismatch {uuid4()}",
            )
            session.add(other_company)
            await session.flush()
            event.company_id = other_company.id
        elif tampered_field == "event_validation_outcome":
            event.validation_outcome = str(tampered_value)
        else:
            event.safe_payload = {
                **event.safe_payload,
                tampered_field: tampered_value,
            }
        await session.commit()

    processor = BillingWebhookProcessor(session_factory, "paymob", policy=policy)
    await processor._process_claimed_event(ingested.event_id)
    async with session_factory() as session:
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        payment = await session.get(Payment, checkout.payment_id)
        subscription = await session.scalar(
            select(Subscription).where(Subscription.company_id == actor.company_id)
        )
        audit = await session.scalar(
            select(BillingAuditEvent).where(
                BillingAuditEvent.action == "webhook.processing_rejected",
            )
        )
        assert event is not None and payment is not None and subscription is not None
        assert event.status == "quarantined"
        assert event.last_error_category == expected_reason
        assert payment.status == "pending"
        assert subscription.status == "incomplete"
        assert subscription.current_period_end is None
        assert audit is not None
        assert audit.safe_metadata["rejection_reason"] == expected_reason

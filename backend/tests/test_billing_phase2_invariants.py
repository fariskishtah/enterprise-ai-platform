"""Fail-closed billing Phase 2 contract invariants.

These tests intentionally exercise provider truth and return correlation without
real credentials, customer data, or browser redirect assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.billing.providers import PaymentProviderError, ProviderTransactionTruth
from app.billing.providers.paymob import (
    PaymobConfiguration,
    PaymobPaymentProvider,
    calculate_transaction_hmac,
)
from app.config.settings import Settings
from app.dependencies.billing import get_billing_webhook_queue, get_payment_provider
from app.models.billing import (
    BillingAuditEvent,
    BillingReconciliationResult,
    BillingReconciliationRun,
    BillingWebhookEvent,
    Payment,
    Subscription,
)
from app.models.manufacturing import Company
from app.models.user import User, UserRole
from app.services.billing import (
    BillingConflictError,
    BillingNotFoundError,
    BillingService,
    BillingWebhookProcessor,
)
from app.services.billing_reconciliation import (
    BillingReconciliationError,
    BillingReconciliationService,
)
from pydantic import ValidationError
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


def _configuration(*, sandbox_mode: bool = True) -> PaymobConfiguration:
    return PaymobConfiguration(
        secret_key="sk_test_phase2",
        public_key="pk_test_phase2",
        hmac_secret="phase2-hmac-secret",
        integration_id=123456,
        merchant_id=700001,
        base_url="https://accept.paymob.com",
        webhook_url="https://api.example.test/billing/webhooks/paymob",
        success_url="https://app.example.test/settings/billing/return",
        failure_url="https://app.example.test/settings/billing/return",
        currency="EGP",
        sandbox_mode=sandbox_mode,
        timeout_seconds=1,
        allowed_checkout_hosts=("accept.paymob.com",),
        supported_source_types=("card",),
    )


def _transaction(**overrides: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "amount_cents": 500_000,
        "created_at": "2026-08-03T09:00:00Z",
        "currency": "EGP",
        "error_occured": False,
        "has_parent_transaction": False,
        "id": 900001,
        "integration_id": 123456,
        "is_3d_secure": True,
        "is_auth": False,
        "is_capture": False,
        "is_live": False,
        "is_refunded": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "order": {"id": 800001, "merchant_order_id": str(uuid4())},
        "owner": 700001,
        "pending": False,
        "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
        "success": True,
    }
    obj.update(overrides)
    return obj


def _parse(obj: dict[str, object], *, sandbox_mode: bool = True):
    return PaymobPaymentProvider(
        _configuration(sandbox_mode=sandbox_mode)
    ).parse_webhook(
        {"type": "TRANSACTION", "obj": obj},
        signature=calculate_transaction_hmac(obj, "phase2-hmac-secret"),
    )


def test_callback_is_bound_to_integration_environment_and_merchant() -> None:
    wrong_integration = _parse(_transaction(integration_id=999999))
    assert wrong_integration.validation_outcome == "quarantined_wrong_integration"

    wrong_environment = _parse(_transaction(is_live=True))
    assert wrong_environment.validation_outcome == "quarantined_wrong_environment"

    wrong_merchant = _parse(_transaction(owner=999999))
    assert wrong_merchant.validation_outcome == "quarantined_wrong_merchant"


def test_success_requires_capture_eligible_semantics() -> None:
    standalone = _parse(_transaction())
    assert standalone.decision == "succeeded_eligible"

    authorization = _parse(
        _transaction(is_auth=True, is_capture=False, is_standalone_payment=False)
    )
    assert authorization.decision == "authorized_not_captured"

    ambiguous = _parse(
        _transaction(is_auth=False, is_capture=False, is_standalone_payment=False)
    )
    assert ambiguous.decision == "under_review"
    assert ambiguous.validation_outcome == "quarantined_unsupported_semantics"

    refunded = _parse(_transaction(is_refunded=True))
    assert refunded.decision == "refunded"


def test_commercial_model_fails_closed(settings: Settings) -> None:
    values = settings.model_dump()
    assert Settings.model_validate(values).billing_commercial_model == (
        "prepaid_manual_renewal"
    )

    values["billing_commercial_model"] = "provider_recurring_subscription"
    with pytest.raises(ValidationError, match="recurring"):
        Settings.model_validate(values)

    values["billing_commercial_model"] = "ambiguous"
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


@pytest.mark.anyio
async def test_return_reference_is_tenant_scoped_and_expires(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reference = "phase2-opaque-return-reference"
    payment = Payment(
        company_id=uuid4(),
        provider="paymob",
        purpose="initial",
        amount_minor=100_000,
        currency="EGP",
        status="pending",
        checkout_intent_status="open",
        return_reference_hash=BillingService.hash_return_reference(reference),
        return_reference_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        return_reference_purpose="checkout_return",
        environment="sandbox",
        commercial_model="prepaid_manual_renewal",
        provider_decision="pending",
    )
    async with session_factory() as session:
        session.add(payment)
        await session.commit()
        resolved = await BillingService(session, None).resolve_return_reference(
            company_id=payment.company_id, reference=reference
        )
        assert resolved.id == payment.id

        with pytest.raises(BillingNotFoundError):
            await BillingService(session, None).resolve_return_reference(
                company_id=uuid4(), reference=reference
            )

        payment.return_reference_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(BillingNotFoundError, match="expired"):
            await BillingService(session, None).resolve_return_reference(
                company_id=payment.company_id, reference=reference
            )


class ReconciliationFixtureProvider:
    name = "paymob"

    def __init__(self, transactions: list[ProviderTransactionTruth]) -> None:
        self.transactions = transactions

    async def list_reconciliation_transactions(
        self,
    ) -> list[ProviderTransactionTruth]:
        return self.transactions


class FailingReconciliationProvider:
    name = "paymob"

    async def list_reconciliation_transactions(
        self,
    ) -> list[ProviderTransactionTruth]:
        raise PaymentProviderError("Provider reconciliation timed out.", retryable=True)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (None, None, "matched"),
        ("amount_minor", 1, "amount_mismatch"),
        ("currency", "USD", "currency_mismatch"),
        ("integration_id", 999999, "integration_mismatch"),
        ("environment", "live", "environment_mismatch"),
        ("decision", "failed", "state_mismatch"),
    ],
)
def test_reconciliation_outcome_matrix(
    field: str | None, value: object, expected: str
) -> None:
    payment = Payment(
        company_id=uuid4(),
        provider="paymob",
        provider_payment_id="provider-matrix",
        purpose="renewal",
        amount_minor=500_000,
        currency="EGP",
        status="succeeded",
        checkout_intent_status="completed",
        environment="sandbox",
        commercial_model="prepaid_manual_renewal",
        provider_decision="succeeded_eligible",
        provider_integration_id=123456,
    )
    values: dict[str, object] = {
        "amount_minor": 500_000,
        "currency": "EGP",
        "decision": "succeeded_eligible",
        "integration_id": 123456,
        "environment": "sandbox",
    }
    if field is not None:
        values[field] = value
    truth = ProviderTransactionTruth(
        provider_payment_id="provider-matrix",
        payment_reference=payment.id,
        amount_minor=int(values["amount_minor"]),
        currency=str(values["currency"]),
        decision=values["decision"],  # type: ignore[arg-type]
        integration_id=int(values["integration_id"]),
        environment=values["environment"],  # type: ignore[arg-type]
        occurred_at=datetime.now(UTC),
    )
    assert BillingReconciliationService._outcome(payment, truth) == expected


@pytest.mark.anyio
async def test_reconciliation_reports_provider_and_local_missing_transactions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company = await session.scalar(select(Company).limit(1))
        assert company is not None
        actor = User(
            email="phase2-missing@example.test",
            full_name="Finance Operator",
            company_id=company.id,
            hashed_password="unused",
            role=UserRole.OWNER,
            is_active=True,
            is_email_verified=True,
            is_platform_operator=True,
        )
        payment = Payment(
            company_id=company.id,
            provider="paymob",
            provider_payment_id="provider-locally-known",
            purpose="renewal",
            amount_minor=500_000,
            currency="EGP",
            status="succeeded",
            checkout_intent_status="completed",
            environment="sandbox",
            commercial_model="prepaid_manual_renewal",
            provider_decision="succeeded_eligible",
            provider_integration_id=123456,
        )
        session.add_all([actor, payment])
        await session.commit()
        unknown_truth = ProviderTransactionTruth(
            provider_payment_id="provider-locally-missing",
            payment_reference=None,
            amount_minor=500_000,
            currency="EGP",
            decision="succeeded_eligible",
            integration_id=123456,
            environment="sandbox",
            occurred_at=datetime.now(UTC),
        )
        summary = await BillingReconciliationService(session).run(
            actor=actor,
            provider=ReconciliationFixtureProvider([unknown_truth]),
            environment="sandbox",
            idempotency_key="phase2-reconciliation-missing-0001",
            dry_run=True,
            finance_approval_reference=None,
        )

    assert summary.outcomes == {"provider_missing": 1, "local_missing": 1}


@pytest.mark.anyio
async def test_reconciliation_provider_timeout_and_malformed_truth_fail_safely(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company = await session.scalar(select(Company).limit(1))
        assert company is not None
        actor = User(
            email="phase2-provider-failure@example.test",
            full_name="Finance Operator",
            company_id=company.id,
            hashed_password="unused",
            role=UserRole.OWNER,
            is_active=True,
            is_email_verified=True,
            is_platform_operator=True,
        )
        session.add(actor)
        await session.commit()
        service = BillingReconciliationService(session)
        with pytest.raises(PaymentProviderError, match="timed out"):
            await service.run(
                actor=actor,
                provider=FailingReconciliationProvider(),
                environment="sandbox",
                idempotency_key="phase2-reconciliation-timeout-0001",
                dry_run=True,
                finance_approval_reference=None,
            )
        with pytest.raises(BillingReconciliationError, match="did not complete"):
            await service.run(
                actor=actor,
                provider=ReconciliationFixtureProvider([]),
                environment="sandbox",
                idempotency_key="phase2-reconciliation-timeout-0001",
                dry_run=True,
                finance_approval_reference=None,
            )
        malformed = ProviderTransactionTruth(
            provider_payment_id="malformed-provider-transaction",
            payment_reference=None,
            amount_minor=-1,
            currency="EGP",
            decision="succeeded_eligible",
            integration_id=123456,
            environment="sandbox",
            occurred_at=datetime.now(UTC),
        )
        with pytest.raises(PaymentProviderError, match="malformed"):
            await service.run(
                actor=actor,
                provider=ReconciliationFixtureProvider([malformed]),
                environment="sandbox",
                idempotency_key="phase2-reconciliation-malformed-0001",
                dry_run=True,
                finance_approval_reference=None,
            )
        failed_runs = await session.scalar(
            select(func.count())
            .select_from(BillingReconciliationRun)
            .where(BillingReconciliationRun.status == "failed")
        )

    assert failed_runs == 2


@pytest.mark.anyio
async def test_reconciliation_is_dry_run_idempotent_and_append_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company = await session.scalar(select(Company).limit(1))
        assert company is not None
        actor = User(
            email="phase2-reconciliation@example.test",
            full_name="Finance Operator",
            company_id=company.id,
            hashed_password="unused",
            role=UserRole.OWNER,
            is_active=True,
            is_email_verified=True,
            is_platform_operator=True,
        )
        payment = Payment(
            company_id=company.id,
            provider="paymob",
            provider_payment_id="provider-9001",
            purpose="renewal",
            amount_minor=500_000,
            currency="EGP",
            status="pending",
            checkout_intent_status="open",
            environment="sandbox",
            commercial_model="prepaid_manual_renewal",
            provider_decision="pending",
            provider_integration_id=123456,
        )
        session.add_all([actor, payment])
        await session.commit()
        truth = ProviderTransactionTruth(
            provider_payment_id="provider-9001",
            payment_reference=payment.id,
            amount_minor=500_000,
            currency="EGP",
            decision="succeeded_eligible",
            integration_id=123456,
            environment="sandbox",
            occurred_at=datetime.now(UTC),
            merchant_id="700001",
        )
        service = BillingReconciliationService(session)
        first = await service.run(
            actor=actor,
            provider=ReconciliationFixtureProvider([truth]),
            environment="sandbox",
            idempotency_key="phase2-reconciliation-dry-0001",
            dry_run=True,
            finance_approval_reference=None,
        )
        replay = await service.run(
            actor=actor,
            provider=ReconciliationFixtureProvider([truth]),
            environment="sandbox",
            idempotency_key="phase2-reconciliation-dry-0001",
            dry_run=True,
            finance_approval_reference=None,
        )
        await session.refresh(payment)
        result_count = await session.scalar(
            select(func.count()).select_from(BillingReconciliationResult)
        )

    assert first.outcomes == {"state_mismatch": 1}
    assert replay.run_id == first.run_id
    assert replay.reused is True
    assert payment.provider_decision == "pending"
    assert result_count == 1


@pytest.mark.anyio
async def test_reconciliation_compensation_requires_approval_and_is_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company = await session.scalar(select(Company).limit(1))
        assert company is not None
        actor = User(
            email="phase2-compensation@example.test",
            full_name="Finance Operator",
            company_id=company.id,
            hashed_password="unused",
            role=UserRole.OWNER,
            is_active=True,
            is_email_verified=True,
            is_platform_operator=True,
        )
        payment = Payment(
            company_id=company.id,
            provider="paymob",
            provider_payment_id="provider-9002",
            purpose="renewal",
            amount_minor=500_000,
            currency="EGP",
            status="pending",
            checkout_intent_status="open",
            checkout_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            environment="sandbox",
            commercial_model="prepaid_manual_renewal",
            provider_decision="pending",
            provider_integration_id=123456,
        )
        session.add_all([actor, payment])
        await session.commit()
        truth = ProviderTransactionTruth(
            provider_payment_id="provider-9002",
            payment_reference=payment.id,
            amount_minor=500_000,
            currency="EGP",
            decision="succeeded_eligible",
            integration_id=123456,
            environment="sandbox",
            occurred_at=datetime.now(UTC),
        )
        summary = await BillingReconciliationService(session).run(
            actor=actor,
            provider=ReconciliationFixtureProvider([truth]),
            environment="sandbox",
            idempotency_key="phase2-reconciliation-apply-0001",
            dry_run=False,
            finance_approval_reference="FIN-2048",
        )
        event = await session.get(
            BillingWebhookEvent, summary.compensating_event_ids[0]
        )
        audit = await session.scalar(
            select(BillingAuditEvent).where(
                BillingAuditEvent.action == "billing.reconciliation_compensating_event"
            )
        )

    assert summary.outcomes == {"corrected_by_compensating_event": 1}
    assert event is not None and event.status == "queued"
    assert audit is not None
    assert audit.safe_metadata["finance_approval_reference"] == "FIN-2048"


@pytest.mark.anyio
async def test_new_checkout_supersedes_old_and_old_success_cannot_grant_access(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        service = BillingService(session, provider)
        older = await service.create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="phase2-supersession-old-0001",
        )
        newer = await service.create_checkout(
            actor=actor,
            plan_code="professional",
            billing_details=_billing_details(),
            idempotency_key="phase2-supersession-new-0001",
        )
        old_payment = await session.get(Payment, older.payment_id)
        new_payment = await session.get(Payment, newer.payment_id)
        assert old_payment is not None and new_payment is not None
        assert old_payment.checkout_intent_status == "superseded"
        assert old_payment.superseded_by_payment_id == new_payment.id
        assert new_payment.checkout_intent_status == "open"
        provider.webhooks["old-paid"] = _event(
            old_payment, fixture="old-paid", state="succeeded"
        )
        ingested = await service.ingest_webhook(
            {"fixture": "old-paid"}, signature="valid"
        )

    await BillingWebhookProcessor(session_factory, "paymob").execute(ingested.event_id)
    async with session_factory() as session:
        old_payment = await session.get(Payment, older.payment_id)
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        subscription = await session.scalar(
            select(Subscription).where(Subscription.company_id == actor.company_id)
        )

    assert old_payment is not None and event is not None and subscription is not None
    assert old_payment.provider_decision == "succeeded_eligible"
    assert event.status == "quarantined"
    assert event.last_error == "manual_review_required"
    assert subscription.status == "incomplete"

    actor.is_platform_operator = True
    async with session_factory() as session:
        with pytest.raises(BillingConflictError, match="not eligible"):
            await BillingService(session, provider).replay_webhook_event(
                actor=actor,
                company_id=actor.company_id,
                event_id=ingested.event_id,
                reason="Superseded checkout must remain quarantined",
            )
        replay_audit = await session.scalar(
            select(BillingAuditEvent).where(
                BillingAuditEvent.action == "webhook.replay_rejected"
            )
        )
        assert replay_audit is not None


@pytest.mark.anyio
async def test_expired_checkout_cannot_be_reused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        service = BillingService(session, provider)
        checkout = await service.create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="phase2-expired-checkout-0001",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        payment.checkout_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(BillingConflictError, match="expired"):
            await service.create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key="phase2-expired-checkout-0001",
            )
        provider.webhooks["expired-paid"] = _event(
            payment, fixture="expired-paid", state="succeeded"
        )
        ingested = await service.ingest_webhook(
            {"fixture": "expired-paid"}, signature="valid"
        )

    await BillingWebhookProcessor(session_factory, "paymob").execute(ingested.event_id)
    actor.is_platform_operator = True
    async with session_factory() as session:
        with pytest.raises(BillingConflictError, match="not eligible"):
            await BillingService(session, provider).replay_webhook_event(
                actor=actor,
                company_id=actor.company_id,
                event_id=ingested.event_id,
                reason="Expired checkout must remain quarantined",
            )
        stored_payment = await session.get(Payment, checkout.payment_id)
        event = await session.get(BillingWebhookEvent, ingested.event_id)
        subscription = await session.scalar(
            select(Subscription).where(Subscription.company_id == actor.company_id)
        )
        assert stored_payment is not None and event is not None
        assert subscription is not None
        assert stored_payment.checkout_intent_status == "expired"
        assert event.status == "quarantined"
        assert subscription.status == "incomplete"
        assert subscription.current_period_end is None


@pytest.mark.anyio
async def test_invalid_provider_contract_is_quarantined_with_card_free_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company = await session.scalar(select(Company).limit(1))
        assert company is not None
        payment = Payment(
            company_id=company.id,
            provider="paymob",
            purpose="initial",
            amount_minor=500_000,
            currency="EGP",
            status="pending",
            checkout_intent_status="open",
            checkout_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            environment="sandbox",
            commercial_model="prepaid_manual_renewal",
            provider_decision="pending",
            provider_integration_id=123456,
            provider_merchant_id="700001",
        )
        session.add(payment)
        await session.commit()
        obj = _transaction(
            integration_id=999999,
            order={"id": 800001, "merchant_order_id": str(payment.id)},
        )
        provider = PaymobPaymentProvider(_configuration())
        result = await BillingService(session, provider).ingest_webhook(
            {"type": "TRANSACTION", "obj": obj},
            signature=calculate_transaction_hmac(obj, "phase2-hmac-secret"),
        )
        event = await session.get(BillingWebhookEvent, result.event_id)

    assert result.outcome == "quarantined_wrong_integration"
    assert result.should_enqueue is False
    assert event is not None and event.status == "quarantined"
    assert event.safe_payload is not None
    assert "pan" not in str(event.safe_payload).lower()
    assert "hmac" not in str(event.safe_payload).lower()


@pytest.mark.anyio
async def test_reconciliation_route_is_platform_operator_only(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    provider = ReconciliationFixtureProvider([])
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
            email="phase2-platform-route@example.com",
        )
        denied = await client.post(
            "/billing/platform/reconciliation/runs",
            headers={**headers, "Idempotency-Key": "phase2-platform-denied-0001"},
            json={"dry_run": True},
        )
        assert denied.status_code == 403

        async with session_factory() as session:
            operator = await session.scalar(
                select(User).where(User.email == "phase2-platform-route@example.com")
            )
            assert operator is not None
            operator.is_platform_operator = True
            await session.commit()

        allowed = await client.post(
            "/billing/platform/reconciliation/runs",
            headers={**headers, "Idempotency-Key": "phase2-platform-allowed-0001"},
            json={"dry_run": True},
        )
        assert allowed.status_code == 201, allowed.text
        assert allowed.json()["outcomes"] == {}

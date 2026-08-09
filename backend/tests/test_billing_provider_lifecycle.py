"""Durability, idempotency, and ordering tests around payment providers."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.billing.providers import (
    CheckoutRequest,
    HostedCheckout,
    PaymentProviderError,
    ProviderWebhook,
)
from app.config.settings import Settings
from app.db.base import Base
from app.dependencies.billing import get_billing_webhook_queue, get_payment_provider
from app.models.billing import BillingPlan, BillingWebhookEvent, Payment
from app.models.manufacturing import Company
from app.models.user import User, UserRole
from app.repositories.billing import BillingRepository
from app.services.billing import (
    BillingConflictError,
    BillingDetails,
    BillingNotFoundError,
    BillingService,
    BillingStateError,
    BillingWebhookProcessor,
    CheckoutUnresolvedError,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.ai_api_support import ai_api_client, auth_headers


class FixtureProvider:
    name = "paymob"

    def __init__(self) -> None:
        self.checkout_requests: list[CheckoutRequest] = []
        self.webhooks: dict[str, ProviderWebhook] = {}
        self.checkout_error: PaymentProviderError | None = None
        self.provider_order_id: str | None = None

    async def create_checkout(self, request: CheckoutRequest) -> HostedCheckout:
        self.checkout_requests.append(request)
        if self.checkout_error is not None:
            raise self.checkout_error
        return HostedCheckout(
            provider_checkout_id=f"pi_{request.reference}",
            checkout_url=f"https://accept.paymob.com/unifiedcheckout/{request.reference}",
            provider_order_id=self.provider_order_id,
        )

    def parse_webhook(
        self, payload: dict[str, object], *, signature: str
    ) -> ProviderWebhook:
        _ = signature
        return self.webhooks[str(payload["fixture"])]


class RecordingBillingQueue:
    def __init__(self) -> None:
        self.event_ids: list[UUID] = []

    def enqueue(self, event_id: UUID) -> str:
        self.event_ids.append(event_id)
        return str(event_id)


class BlockingCheckoutProvider(FixtureProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def create_checkout(self, request: CheckoutRequest) -> HostedCheckout:
        self.checkout_requests.append(request)
        self.started.set()
        await self.release.wait()
        return HostedCheckout(
            provider_checkout_id=f"pi_{request.reference}",
            checkout_url=f"https://accept.paymob.com/unifiedcheckout/{request.reference}",
        )


def _billing_details() -> BillingDetails:
    return BillingDetails(
        first_name="Factory",
        last_name="Owner",
        phone_number="+201001234567",
        city="Cairo",
        country="EG",
        street="Industrial Zone",
    )


async def _actor(session_factory: async_sessionmaker[AsyncSession]) -> User:
    async with session_factory() as session:
        company = await session.scalar(select(Company).limit(1))
        assert company is not None
        actor = User(
            email=f"billing-{uuid4()}@example.com",
            full_name="Factory Owner",
            company_id=company.id,
            hashed_password="not-used",
            role=UserRole.OWNER,
            is_active=True,
            is_email_verified=True,
        )
        session.add(actor)
        await session.commit()
        return actor


@pytest.mark.anyio
async def test_checkout_resolves_price_server_side_and_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    provider.provider_order_id = "provider-order-contract"
    async with session_factory() as session:
        service = BillingService(session, provider)
        first = await service.create_checkout(
            actor=actor,
            plan_code="professional",
            billing_details=_billing_details(),
            idempotency_key="checkout-contract-0001",
        )
        second = await service.create_checkout(
            actor=actor,
            plan_code="professional",
            billing_details=_billing_details(),
            idempotency_key="checkout-contract-0001",
        )
        payment = await session.get(Payment, first.payment_id)
        assert payment is not None
        assert payment.provider_order_id == "provider-order-contract"

    assert first.payment_id == second.payment_id
    assert first.plan.monthly_price_minor == 500_000
    assert second.reused is True
    assert len(provider.checkout_requests) == 1
    assert provider.checkout_requests[0].amount_minor == 500_000
    assert provider.checkout_requests[0].currency == "EGP"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("plan_code", "amount_minor"),
    [("starter", 100_000), ("professional", 500_000), ("enterprise", 1_000_000)],
)
async def test_every_plan_uses_the_server_catalogue_provider_amount(
    session_factory: async_sessionmaker[AsyncSession],
    plan_code: str,
    amount_minor: int,
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code=plan_code,
            billing_details=_billing_details(),
            idempotency_key=f"checkout-every-plan-{plan_code}",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        assert payment.amount_minor == amount_minor
        assert payment.currency == "EGP"
    assert len(provider.checkout_requests) == 1
    assert provider.checkout_requests[0].amount_minor == amount_minor
    assert provider.checkout_requests[0].currency == "EGP"


@pytest.mark.anyio
@pytest.mark.parametrize("defect", ["disabled", "price_drift"])
async def test_checkout_fails_closed_for_disabled_or_drifted_database_plan(
    session_factory: async_sessionmaker[AsyncSession], defect: str
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        session.add(
            BillingPlan(
                code="starter",
                name="Starter",
                currency="EGP",
                monthly_price_minor=(1 if defect == "price_drift" else 100_000),
                is_active=defect != "disabled",
            )
        )
        await session.commit()
        expected = BillingNotFoundError if defect == "disabled" else BillingStateError
        with pytest.raises(expected):
            await BillingService(session, provider).create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key=f"checkout-plan-contract-{defect}",
            )
    assert provider.checkout_requests == []


@pytest.mark.anyio
async def test_checkout_rejects_invalid_plan_and_company(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    async with session_factory() as session:
        service = BillingService(session, FixtureProvider())
        with pytest.raises(BillingNotFoundError, match="plan"):
            await service.create_checkout(
                actor=actor,
                plan_code="invented",
                billing_details=_billing_details(),
                idempotency_key="checkout-contract-0002",
            )
        actor.company_id = uuid4()
        with pytest.raises(BillingNotFoundError, match="company"):
            await service.create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key="checkout-contract-0003",
            )


@pytest.mark.anyio
async def test_provider_failure_is_persisted_without_fake_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    provider.checkout_error = PaymentProviderError("timeout", retryable=True)
    async with session_factory() as session:
        with pytest.raises(PaymentProviderError):
            await BillingService(session, provider).create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key="checkout-contract-0004",
            )
        payment = await session.scalar(
            select(Payment).where(Payment.idempotency_key == "checkout-contract-0004")
        )
        assert payment is not None
        assert payment.status == "provider_error"
        assert payment.provider_payment_id is None
        provider.checkout_error = None
        with pytest.raises(CheckoutUnresolvedError, match="still verifying"):
            await BillingService(session, provider).create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key="checkout-contract-0004",
            )
        with pytest.raises(CheckoutUnresolvedError, match="still verifying"):
            await BillingService(session, provider).create_checkout(
                actor=actor,
                plan_code="professional",
                billing_details=_billing_details(),
                idempotency_key="checkout-contract-0004-other-tab",
            )
        assert len(provider.checkout_requests) == 1


@pytest.mark.anyio
async def test_concurrent_checkout_requests_create_one_provider_checkout(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = BlockingCheckoutProvider()

    async def create_first_checkout() -> object:
        async with session_factory() as session:
            return await BillingService(session, provider).create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key="checkout-concurrency-first",
            )

    first = asyncio.create_task(create_first_checkout())
    await provider.started.wait()
    try:
        async with session_factory() as session:
            with pytest.raises(CheckoutUnresolvedError) as raised:
                await BillingService(session, provider).create_checkout(
                    actor=actor,
                    plan_code="professional",
                    billing_details=_billing_details(),
                    idempotency_key="checkout-concurrency-second",
                )
            assert raised.value.checkout_intent_status == "open"
            assert raised.value.provider_decision == "pending"
    finally:
        provider.release.set()
    await first

    async with session_factory() as session:
        payment_count = await session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.company_id == actor.company_id)
        )
    assert payment_count == 1
    assert len(provider.checkout_requests) == 1


@pytest.mark.anyio
async def test_local_checkout_cancellation_does_not_unlock_another_payment(
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
            idempotency_key="checkout-local-cancel-first",
        )
        cancelled = await service.cancel_checkout(
            actor=actor, payment_id=checkout.payment_id
        )
        assert cancelled.checkout_intent_status == "cancelled"
        assert cancelled.status == "pending"
        assert cancelled.provider_decision == "pending"
        with pytest.raises(CheckoutUnresolvedError) as raised:
            await service.create_checkout(
                actor=actor,
                plan_code="professional",
                billing_details=_billing_details(),
                idempotency_key="checkout-local-cancel-second",
            )
        assert raised.value.payment_id == checkout.payment_id
    assert len(provider.checkout_requests) == 1


@pytest.mark.anyio
async def test_only_definitive_provider_failure_unlocks_another_checkout(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        service = BillingService(session, provider)
        first = await service.create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="checkout-terminal-failure-first",
        )
        payment = await session.get(Payment, first.payment_id)
        assert payment is not None
        provider.webhooks["terminal-failure"] = _event(
            payment, fixture="terminal-failure", state="failed"
        )
        ingested = await service.ingest_webhook(
            {"fixture": "terminal-failure"}, signature="valid"
        )
    await BillingWebhookProcessor(session_factory, "paymob").execute(ingested.event_id)

    async with session_factory() as session:
        second = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="professional",
            billing_details=_billing_details(),
            idempotency_key="checkout-after-terminal-failure",
        )
        assert second.payment_id != first.payment_id
    assert len(provider.checkout_requests) == 2


@pytest.mark.anyio
async def test_business_quarantine_keeps_checkout_blocked(
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
            idempotency_key="checkout-business-quarantine-first",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks["business-quarantine"] = replace(
            _event(payment, fixture="business-quarantine", state="succeeded"),
            validation_outcome="quarantined_wrong_merchant",
        )
        ingested = await service.ingest_webhook(
            {"fixture": "business-quarantine"}, signature="valid"
        )
        assert ingested.should_enqueue is False
        with pytest.raises(CheckoutUnresolvedError):
            await service.create_checkout(
                actor=actor,
                plan_code="professional",
                billing_details=_billing_details(),
                idempotency_key="checkout-business-quarantine-second",
            )
    assert len(provider.checkout_requests) == 1


@pytest.mark.anyio
async def test_checkout_and_webhook_api_contracts(
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
        owner_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="billing-api-owner@example.com",
        )
        checkout_payload = {
            "plan_code": "starter",
            "billing_details": {
                "first_name": "Factory",
                "last_name": "Owner",
                "phone_number": "+201001234567",
                "city": "Cairo",
                "country": "EG",
                "street": "Industrial Zone",
            },
        }
        created = await client.post(
            "/billing/checkouts",
            headers={**owner_headers, "Idempotency-Key": "api-checkout-contract-001"},
            json=checkout_payload,
        )
        replayed = await client.post(
            "/billing/checkouts",
            headers={**owner_headers, "Idempotency-Key": "api-checkout-contract-001"},
            json=checkout_payload,
        )
        blocked_other_tab = await client.post(
            "/billing/checkouts",
            headers={**owner_headers, "Idempotency-Key": "api-checkout-other-tab-01"},
            json={**checkout_payload, "plan_code": "professional"},
        )
        invalid_plan = await client.post(
            "/billing/checkouts",
            headers={**owner_headers, "Idempotency-Key": "api-checkout-contract-002"},
            json={**checkout_payload, "plan_code": "unknown"},
        )
        supplied_money = await client.post(
            "/billing/checkouts",
            headers={**owner_headers, "Idempotency-Key": "api-checkout-contract-003"},
            json={**checkout_payload, "amount_minor": 1, "currency": "USD"},
        )

        assert created.status_code == 201, created.text
        assert created.json()["amount_minor"] == 100_000
        assert created.json()["currency"] == "EGP"
        assert replayed.status_code == 201
        assert replayed.json()["payment_id"] == created.json()["payment_id"]
        assert replayed.json()["reused"] is True
        assert blocked_other_tab.status_code == 409
        assert blocked_other_tab.json()["detail"] == {
            "code": "checkout_unresolved",
            "message": (
                "We're still verifying your existing payment. "
                "Please don't try again yet."
            ),
            "payment_id": created.json()["payment_id"],
            "checkout_intent_status": "open",
            "provider_decision": "pending",
        }
        assert invalid_plan.status_code == 404
        assert supplied_money.status_code == 422

        payment_id = UUID(created.json()["payment_id"])
        async with session_factory() as session:
            payment = await session.get(Payment, payment_id)
            assert payment is not None
            provider.webhooks["api-success"] = _event(
                payment, fixture="api-success", state="succeeded"
            )
        webhook = await client.post(
            "/billing/webhooks/paymob?hmac=fixture",
            json={"fixture": "api-success"},
        )
        duplicate = await client.post(
            "/billing/webhooks/paymob?hmac=fixture",
            json={"fixture": "api-success"},
        )
        assert webhook.status_code == 202, webhook.text
        assert duplicate.status_code == 202
        assert duplicate.json()["duplicate"] is True
        assert len(queue.event_ids) == 1


def _event(
    payment: Payment,
    *,
    fixture: str,
    state: str,
    amount_minor: int | None = None,
    currency: str | None = None,
    occurred_at: datetime | None = None,
) -> ProviderWebhook:
    return ProviderWebhook(
        provider_event_id=f"transaction:{fixture}:{state}",
        raw_provider_event_id=fixture,
        event_type=f"transaction.{state}",
        payment_reference=payment.id,
        provider_payment_id=fixture,
        amount_minor=amount_minor or payment.amount_minor,
        currency=currency or payment.currency,
        state=state,  # type: ignore[arg-type]
        occurred_at=occurred_at or datetime.now(UTC),
        failure_code="declined" if state == "failed" else None,
    )


async def _ingest_and_process(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FixtureProvider,
    fixture: str,
) -> UUID:
    async with session_factory() as session:
        result = await BillingService(session, provider).ingest_webhook(
            {"fixture": fixture}, signature="valid"
        )
    await BillingWebhookProcessor(session_factory, "paymob").execute(result.event_id)
    return result.event_id


@pytest.mark.anyio
async def test_duplicate_success_webhook_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="checkout-contract-0005",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks["success"] = _event(
            payment, fixture="success", state="succeeded"
        )

    event_id = await _ingest_and_process(session_factory, provider, "success")
    async with session_factory() as session:
        duplicate = await BillingService(session, provider).ingest_webhook(
            {"fixture": "success"}, signature="valid"
        )
        payment = await session.get(Payment, checkout.payment_id)
        event = await session.get(BillingWebhookEvent, event_id)
        assert payment is not None and event is not None
        assert duplicate.duplicate is True
        assert duplicate.should_enqueue is False
        assert payment.status == "succeeded"
        assert event.attempts == 1
        with pytest.raises(BillingConflictError, match="no longer"):
            await BillingService(session, provider).create_checkout(
                actor=actor,
                plan_code="starter",
                billing_details=_billing_details(),
                idempotency_key="checkout-contract-0005",
            )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("amount_minor", 1, "quarantined_wrong_amount"),
        ("currency", "USD", "quarantined_wrong_currency"),
    ],
)
async def test_incorrect_webhook_money_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
    field: str,
    value: object,
    reason: str,
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key=f"checkout-money-{field}",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        kwargs = {field: value}
        provider.webhooks[field] = _event(
            payment,
            fixture=field,
            state="succeeded",
            **kwargs,  # type: ignore[arg-type]
        )
    event_id = await _ingest_and_process(session_factory, provider, field)
    async with session_factory() as session:
        event = await session.get(BillingWebhookEvent, event_id)
        payment = await session.get(Payment, checkout.payment_id)
        assert event is not None and payment is not None
        assert event.status == "quarantined"
        assert event.last_error == reason
        assert payment.status == "pending"


@pytest.mark.anyio
async def test_failure_then_success_and_out_of_order_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key="checkout-contract-0006",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks["failed"] = _event(payment, fixture="failed", state="failed")
        provider.webhooks["succeeded"] = _event(
            payment, fixture="succeeded", state="succeeded"
        )
        provider.webhooks["late-failure"] = _event(
            payment, fixture="late-failure", state="failed"
        )

    await _ingest_and_process(session_factory, provider, "failed")
    await _ingest_and_process(session_factory, provider, "succeeded")
    stale_event_id = await _ingest_and_process(
        session_factory, provider, "late-failure"
    )
    async with session_factory() as session:
        payment = await session.get(Payment, checkout.payment_id)
        stale = await session.get(BillingWebhookEvent, stale_event_id)
        assert payment is not None and stale is not None
        assert payment.status == "succeeded"
        assert stale.status == "quarantined"
        assert stale.last_error == "out_of_order"


@pytest.mark.anyio
@pytest.mark.parametrize("terminal_state", ["refunded", "reversed"])
async def test_refund_and_reversal_override_success(
    session_factory: async_sessionmaker[AsyncSession], terminal_state: str
) -> None:
    actor = await _actor(session_factory)
    provider = FixtureProvider()
    async with session_factory() as session:
        checkout = await BillingService(session, provider).create_checkout(
            actor=actor,
            plan_code="starter",
            billing_details=_billing_details(),
            idempotency_key=f"checkout-{terminal_state}",
        )
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        provider.webhooks["success"] = _event(
            payment, fixture=f"success-{terminal_state}", state="succeeded"
        )
        provider.webhooks[terminal_state] = _event(
            payment, fixture=terminal_state, state=terminal_state
        )
    await _ingest_and_process(session_factory, provider, "success")
    await _ingest_and_process(session_factory, provider, terminal_state)
    async with session_factory() as session:
        payment = await session.get(Payment, checkout.payment_id)
        assert payment is not None
        assert payment.status == terminal_state


@pytest.mark.anyio
async def test_concurrent_duplicate_enqueue_claim_has_single_winner(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    event_id = uuid4()
    async with factory() as session:
        session.add(
            BillingWebhookEvent(
                id=event_id,
                provider="paymob",
                provider_event_id="transaction:concurrent:succeeded",
                raw_provider_event_id="concurrent",
                event_type="transaction.succeeded",
                payload_hash="a" * 64,
                safe_payload={},
                status="received",
            )
        )
        await session.commit()

    async def claim() -> bool:
        async with factory() as session:
            claimed = await BillingRepository(session).claim_event_for_enqueue(event_id)
            await session.commit()
            return claimed

    try:
        results = await asyncio.gather(claim(), claim())
        assert sorted(results) == [False, True]
    finally:
        await engine.dispose()

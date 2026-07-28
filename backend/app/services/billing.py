"""Hosted-checkout orchestration and durable webhook processing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.catalog import PlanDefinition, get_plan
from app.billing.providers import (
    CheckoutRequest,
    HostedCheckout,
    PaymentProvider,
    PaymentProviderError,
    ProviderWebhook,
)
from app.models.billing import BillingWebhookEvent, Payment
from app.models.user import User
from app.repositories.billing import BillingRepository


class BillingError(RuntimeError):
    """Base billing use-case failure."""


class BillingNotFoundError(BillingError):
    """A plan or tenant-owned payment does not exist."""


class BillingConflictError(BillingError):
    """An idempotency key or lifecycle transition conflicts."""


class BillingWebhookPayloadError(BillingError):
    """A duplicate event identifier arrived with different content."""


@dataclass(frozen=True, slots=True)
class BillingDetails:
    first_name: str
    last_name: str
    phone_number: str
    city: str
    country: str
    street: str


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    payment_id: UUID
    plan: PlanDefinition
    status: str
    checkout: HostedCheckout
    reused: bool


@dataclass(frozen=True, slots=True)
class WebhookIngestResult:
    event_id: UUID
    duplicate: bool
    should_enqueue: bool


class BillingService:
    def __init__(
        self,
        session: AsyncSession,
        provider: PaymentProvider,
    ) -> None:
        self._session = session
        self._provider = provider
        self._repository = BillingRepository(session)

    async def create_checkout(
        self,
        *,
        actor: User,
        plan_code: str,
        billing_details: BillingDetails,
        idempotency_key: str,
    ) -> CheckoutResult:
        plan = get_plan(plan_code)
        if plan is None:
            raise BillingNotFoundError("The requested billing plan does not exist.")
        if not await self._repository.company_is_billable(actor.company_id):
            raise BillingNotFoundError("The billing company does not exist.")
        created_here = False
        existing = await self._repository.get_by_idempotency(
            actor.company_id, idempotency_key
        )
        if existing is None:
            payment = Payment(
                id=uuid4(),
                company_id=actor.company_id,
                provider=self._provider.name,
                idempotency_key=idempotency_key,
                plan_code=plan.code,
                amount_minor=plan.monthly_price_minor,
                currency=plan.currency,
                status="creating",
            )
            self._repository.add_payment(payment)
            try:
                await self._session.commit()
            except IntegrityError:
                await self._session.rollback()
                existing = await self._repository.get_by_idempotency(
                    actor.company_id, idempotency_key
                )
                if existing is None:
                    raise
            else:
                existing = payment
                created_here = True
        payment = existing
        if payment.plan_code != plan.code:
            raise BillingConflictError(
                "The idempotency key was already used for another plan."
            )
        if (
            payment.status == "pending"
            and payment.checkout_url
            and payment.provider_checkout_id
        ):
            return self._checkout_result(payment, plan, reused=True)
        if payment.status == "provider_error":
            claimed = await self._repository.claim_payment_retry(payment.id)
            await self._session.commit()
            if not claimed:
                raise BillingConflictError("Checkout creation is already in progress.")
            created_here = True
        if payment.status == "creating" and not created_here:
            raise BillingConflictError("Checkout creation is already in progress.")
        if payment.status != "creating":
            raise BillingConflictError(
                "This payment can no longer create a hosted checkout."
            )
        try:
            checkout = await self._provider.create_checkout(
                CheckoutRequest(
                    reference=payment.id,
                    plan_code=plan.code,
                    plan_name=plan.name,
                    amount_minor=plan.monthly_price_minor,
                    currency=plan.currency,
                    email=actor.email,
                    first_name=billing_details.first_name,
                    last_name=billing_details.last_name,
                    phone_number=billing_details.phone_number,
                    city=billing_details.city,
                    country=billing_details.country,
                    street=billing_details.street,
                )
            )
        except PaymentProviderError:
            payment.status = "provider_error"
            payment.failure_code = "checkout_provider_error"
            await self._session.commit()
            raise
        payment.provider_checkout_id = checkout.provider_checkout_id
        payment.checkout_url = checkout.checkout_url
        payment.status = "pending"
        payment.failure_code = None
        await self._session.commit()
        return CheckoutResult(
            payment_id=payment.id,
            plan=plan,
            status=payment.status,
            checkout=checkout,
            reused=False,
        )

    @staticmethod
    def _checkout_result(
        payment: Payment, plan: PlanDefinition, *, reused: bool
    ) -> CheckoutResult:
        assert payment.provider_checkout_id is not None
        assert payment.checkout_url is not None
        return CheckoutResult(
            payment_id=payment.id,
            plan=plan,
            status=payment.status,
            checkout=HostedCheckout(
                provider_checkout_id=payment.provider_checkout_id,
                checkout_url=payment.checkout_url,
            ),
            reused=reused,
        )

    async def cancel_checkout(self, *, actor: User, payment_id: UUID) -> Payment:
        payment = await self._repository.get_company_payment(
            payment_id, actor.company_id, lock=True
        )
        if payment is None:
            raise BillingNotFoundError("The payment does not exist.")
        if payment.status in {"creating", "pending", "provider_error"}:
            payment.status = "cancelled"
            payment.failure_code = None
            await self._session.commit()
            return payment
        if payment.status == "cancelled":
            return payment
        raise BillingConflictError("A completed payment cannot be cancelled locally.")

    async def ingest_webhook(
        self, payload: dict[str, object], *, signature: str
    ) -> WebhookIngestResult:
        normalized = self._provider.parse_webhook(payload, signature=signature)
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await self._repository.get_event_by_provider_id(
            self._provider.name, normalized.provider_event_id
        )
        duplicate = existing is not None
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise BillingWebhookPayloadError(
                    "The provider event identifier was reused with different content."
                )
            event = existing
        else:
            event = BillingWebhookEvent(
                provider=self._provider.name,
                provider_event_id=normalized.provider_event_id,
                raw_provider_event_id=normalized.raw_provider_event_id,
                event_type=normalized.event_type,
                payload_hash=payload_hash,
                safe_payload=self._safe_payload(normalized),
                status="received",
            )
            self._repository.add_event(event)
            try:
                await self._session.flush()
            except IntegrityError as exc:
                await self._session.rollback()
                conflicting_event = await self._repository.get_event_by_provider_id(
                    self._provider.name, normalized.provider_event_id
                )
                if conflicting_event is None:
                    raise
                event = conflicting_event
                duplicate = True
                if event.payload_hash != payload_hash:
                    raise BillingWebhookPayloadError(
                        "The provider event identifier was reused with different "
                        "content."
                    ) from exc
        should_enqueue = await self._repository.claim_event_for_enqueue(event.id)
        await self._session.commit()
        return WebhookIngestResult(
            event_id=event.id,
            duplicate=duplicate,
            should_enqueue=should_enqueue,
        )

    async def release_failed_enqueue(self, event_id: UUID) -> None:
        await self._repository.release_event_enqueue(event_id)
        await self._session.commit()

    @staticmethod
    def _safe_payload(event: ProviderWebhook) -> dict[str, object]:
        return {
            "payment_reference": str(event.payment_reference),
            "provider_payment_id": event.provider_payment_id,
            "amount_minor": event.amount_minor,
            "currency": event.currency,
            "state": event.state,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "failure_code": event.failure_code,
            "provider_customer_id": event.provider_customer_id,
        }


_STATE_RANK = {
    "creating": 0,
    "provider_error": 0,
    "pending": 1,
    "failed": 2,
    "cancelled": 3,
    "succeeded": 4,
    "reversed": 5,
    "refunded": 6,
}


class BillingWebhookProcessor:
    """Transactionally apply queued normalized callbacks exactly once."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], provider_name: str
    ) -> None:
        self._session_factory = session_factory
        self._provider_name = provider_name

    async def execute(self, event_id: UUID) -> None:
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            event = await repository.get_event(event_id, lock=True)
            if event is None or event.status in {"processed", "ignored"}:
                return
            event.status = "processing"
            event.attempts += 1
            payload = event.safe_payload or {}
            try:
                reference = UUID(str(payload["payment_reference"]))
                provider_payment_id = str(payload["provider_payment_id"])
                amount_value = payload["amount_minor"]
                if not isinstance(amount_value, (int, str)) or isinstance(
                    amount_value, bool
                ):
                    raise ValueError("Invalid amount")
                amount_minor = int(amount_value)
                currency = str(payload["currency"])
                state = str(payload["state"])
                occurred_value = payload.get("occurred_at")
                occurred_at = (
                    datetime.fromisoformat(str(occurred_value))
                    if occurred_value
                    else None
                )
            except (KeyError, TypeError, ValueError):
                event.status = "ignored"
                event.last_error = "invalid_normalized_payload"
                event.processed_at = datetime.now(UTC)
                await session.commit()
                return
            payment = await repository.get_payment(reference, lock=True)
            if payment is None or payment.provider != self._provider_name:
                event.status = "ignored"
                event.last_error = "payment_not_found"
            elif payment.amount_minor != amount_minor:
                event.status = "ignored"
                event.last_error = "amount_mismatch"
            elif payment.currency != currency:
                event.status = "ignored"
                event.last_error = "currency_mismatch"
            elif state not in _STATE_RANK:
                event.status = "ignored"
                event.last_error = "unknown_state"
            elif self._is_stale(payment, state, occurred_at):
                event.status = "ignored"
                event.last_error = "out_of_order"
            else:
                payment.provider_payment_id = provider_payment_id
                payment.status = state
                payment.failure_code = (
                    str(payload.get("failure_code"))[:80]
                    if payload.get("failure_code")
                    else None
                )
                payment.provider_occurred_at = occurred_at
                event.status = "processed"
                event.last_error = None
            event.processed_at = datetime.now(UTC)
            await session.commit()

    @staticmethod
    def _is_stale(payment: Payment, state: str, occurred_at: datetime | None) -> bool:
        current_rank = _STATE_RANK.get(payment.status, -1)
        incoming_rank = _STATE_RANK[state]
        if incoming_rank < current_rank:
            return True
        return bool(
            incoming_rank == current_rank
            and occurred_at is not None
            and payment.provider_occurred_at is not None
            and occurred_at < payment.provider_occurred_at
        )

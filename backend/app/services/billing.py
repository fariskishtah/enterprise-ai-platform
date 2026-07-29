"""Hosted checkout, subscription lifecycle, and durable webhook processing."""

from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

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
from app.models.billing import (
    BillingAuditEvent,
    BillingPlan,
    BillingWebhookEvent,
    InvoiceReference,
    Payment,
    Subscription,
)
from app.models.user import User
from app.repositories.billing import BillingRepository


class BillingError(RuntimeError):
    """Base billing use-case failure with a stable public code."""

    code = "billing_error"


class BillingNotFoundError(BillingError):
    code = "billing_not_found"


class BillingConflictError(BillingError):
    code = "billing_conflict"


class BillingWebhookPayloadError(BillingError):
    code = "webhook_payload_conflict"


class BillingStateError(BillingConflictError):
    code = "invalid_subscription_transition"


@dataclass(frozen=True, slots=True)
class BillingPolicy:
    grace_period_days: int = 7
    incomplete_expiry_hours: int = 24
    suspension_expiry_days: int = 30


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
    subscription_id: UUID
    plan: PlanDefinition
    status: str
    checkout: HostedCheckout
    reused: bool
    purpose: str


@dataclass(frozen=True, slots=True)
class WebhookIngestResult:
    event_id: UUID
    duplicate: bool
    should_enqueue: bool


def _next_month(value: datetime) -> datetime:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return value.replace(
        year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class BillingService:
    def __init__(
        self,
        session: AsyncSession,
        provider: PaymentProvider | None,
        *,
        policy: BillingPolicy | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._repository = BillingRepository(session)
        self._policy = policy or BillingPolicy()

    async def create_checkout(
        self,
        *,
        actor: User,
        plan_code: str,
        billing_details: BillingDetails,
        idempotency_key: str,
        expected_change: Literal["upgrade", "downgrade"] | None = None,
    ) -> CheckoutResult:
        provider = self._require_provider()
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
            plan_record = await self._ensure_plan(plan)
            subscription = await self._repository.get_company_subscription(
                actor.company_id, lock=True
            )
            now = datetime.now(UTC)
            if subscription is None:
                if expected_change is not None:
                    raise BillingStateError("A current subscription is required.")
                subscription = Subscription(
                    id=uuid4(),
                    company_id=actor.company_id,
                    plan_id=plan_record.id,
                    provider=provider.name,
                    status="incomplete",
                    status_changed_at=now,
                    version=1,
                )
                self._repository.add_subscription(subscription)
                await self._session.flush()
                purpose = "initial"
                self._audit(
                    company_id=actor.company_id,
                    actor_user_id=actor.id,
                    action="subscription.created",
                    metadata={
                        "subscription_id": str(subscription.id),
                        "to_status": "incomplete",
                        "plan_code": plan.code,
                    },
                )
            else:
                current_plan = await self._repository.get_plan_by_id(
                    subscription.plan_id
                )
                if current_plan is None:
                    raise BillingStateError("The current subscription plan is invalid.")
                if expected_change == "upgrade" and (
                    plan.monthly_price_minor <= current_plan.monthly_price_minor
                ):
                    raise BillingStateError("The requested plan is not an upgrade.")
                if expected_change == "downgrade" and (
                    plan.monthly_price_minor >= current_plan.monthly_price_minor
                ):
                    raise BillingStateError("The requested plan is not a downgrade.")
                if subscription.status == "incomplete":
                    subscription.plan_id = plan_record.id
                    purpose = "initial"
                elif subscription.status in {"cancelled", "expired", "suspended"}:
                    subscription.pending_plan_id = plan_record.id
                    purpose = "reactivation"
                elif plan_record.id != subscription.plan_id:
                    subscription.pending_plan_id = plan_record.id
                    purpose = "plan_change"
                else:
                    purpose = "renewal"

            payment = Payment(
                id=uuid4(),
                company_id=actor.company_id,
                subscription_id=subscription.id,
                provider=provider.name,
                idempotency_key=idempotency_key,
                plan_code=plan.code,
                purpose=purpose,
                amount_minor=plan.monthly_price_minor,
                currency=plan.currency,
                status="creating",
            )
            self._repository.add_payment(payment)
            self._audit(
                company_id=actor.company_id,
                actor_user_id=actor.id,
                action="checkout.requested",
                metadata={
                    "payment_id": str(payment.id),
                    "subscription_id": str(subscription.id),
                    "plan_code": plan.code,
                    "purpose": purpose,
                },
            )
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
        if expected_change is not None and payment.purpose != "plan_change":
            raise BillingStateError("The idempotency key belongs to another action.")
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
            checkout = await provider.create_checkout(
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
            self._audit(
                company_id=payment.company_id,
                actor_user_id=actor.id,
                action="checkout.provider_failed",
                result="failed",
                metadata={"payment_id": str(payment.id)},
            )
            await self._session.commit()
            raise
        payment.provider_checkout_id = checkout.provider_checkout_id
        payment.checkout_url = checkout.checkout_url
        payment.status = "pending"
        payment.failure_code = None
        self._audit(
            company_id=payment.company_id,
            actor_user_id=actor.id,
            action="checkout.created",
            metadata={
                "payment_id": str(payment.id),
                "provider_checkout_id": checkout.provider_checkout_id,
            },
        )
        await self._session.commit()
        assert payment.subscription_id is not None
        return CheckoutResult(
            payment_id=payment.id,
            subscription_id=payment.subscription_id,
            plan=plan,
            status=payment.status,
            checkout=checkout,
            reused=False,
            purpose=payment.purpose,
        )

    async def _ensure_plan(self, plan: PlanDefinition) -> BillingPlan:
        record = await self._repository.get_plan(plan.code)
        if record is not None:
            return record
        record = BillingPlan(
            id=uuid5(NAMESPACE_URL, f"billing-plan:{plan.code}"),
            code=plan.code,
            name=plan.name,
            currency=plan.currency,
            monthly_price_minor=plan.monthly_price_minor,
            is_active=True,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    def _require_provider(self) -> PaymentProvider:
        if self._provider is None:
            raise BillingStateError("A payment provider is required for this action.")
        return self._provider

    @staticmethod
    def _checkout_result(
        payment: Payment, plan: PlanDefinition, *, reused: bool
    ) -> CheckoutResult:
        assert payment.provider_checkout_id is not None
        assert payment.checkout_url is not None
        assert payment.subscription_id is not None
        return CheckoutResult(
            payment_id=payment.id,
            subscription_id=payment.subscription_id,
            plan=plan,
            status=payment.status,
            checkout=HostedCheckout(
                provider_checkout_id=payment.provider_checkout_id,
                checkout_url=payment.checkout_url,
            ),
            reused=reused,
            purpose=payment.purpose,
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
            if payment.subscription_id and payment.purpose in {
                "plan_change",
                "reactivation",
            }:
                subscription = await self._repository.get_subscription(
                    payment.subscription_id, lock=True
                )
                if subscription is not None:
                    subscription.pending_plan_id = None
            self._audit(
                company_id=actor.company_id,
                actor_user_id=actor.id,
                action="checkout.cancelled",
                metadata={"payment_id": str(payment.id)},
            )
            await self._session.commit()
            return payment
        if payment.status == "cancelled":
            return payment
        raise BillingConflictError("A completed payment cannot be cancelled locally.")

    async def current_subscription(self, *, actor: User) -> Subscription | None:
        subscription = await self._repository.get_company_subscription(
            actor.company_id, lock=True
        )
        if subscription is not None and self._reconcile(
            subscription, datetime.now(UTC)
        ):
            await self._session.commit()
        return subscription

    async def cancel_subscription(
        self, *, actor: User, immediate: bool = False
    ) -> Subscription:
        subscription = await self._require_subscription(actor.company_id, lock=True)
        now = datetime.now(UTC)
        self._reconcile(subscription, now)
        if subscription.status not in {"trialing", "active", "past_due"}:
            raise BillingStateError("This subscription cannot be cancelled.")
        if immediate:
            self._transition(
                subscription,
                "cancelled",
                now=now,
                actor_user_id=actor.id,
                action="subscription.cancelled_immediately",
            )
            subscription.current_period_end = now
            subscription.ended_at = now
            subscription.cancel_at_period_end = False
        elif not subscription.cancel_at_period_end:
            subscription.cancel_at_period_end = True
            self._audit(
                company_id=actor.company_id,
                actor_user_id=actor.id,
                action="subscription.cancellation_scheduled",
                metadata={
                    "subscription_id": str(subscription.id),
                    "effective_at": subscription.current_period_end.isoformat()
                    if subscription.current_period_end
                    else None,
                },
            )
        await self._session.commit()
        return subscription

    async def reactivate_subscription(self, *, actor: User) -> Subscription:
        subscription = await self._require_subscription(actor.company_id, lock=True)
        now = datetime.now(UTC)
        self._reconcile(subscription, now)
        if subscription.status not in {"trialing", "active", "past_due"}:
            raise BillingStateError(
                "A new verified payment is required to reactivate this subscription."
            )
        if not subscription.cancel_at_period_end:
            return subscription
        subscription.cancel_at_period_end = False
        self._audit(
            company_id=actor.company_id,
            actor_user_id=actor.id,
            action="subscription.reactivated",
            metadata={"subscription_id": str(subscription.id)},
        )
        await self._session.commit()
        return subscription

    async def reconcile_subscription(self, *, actor: User) -> Subscription:
        subscription = await self._require_subscription(actor.company_id, lock=True)
        changed = self._reconcile(subscription, datetime.now(UTC))
        if changed:
            await self._session.commit()
        return subscription

    async def _require_subscription(
        self, company_id: UUID, *, lock: bool
    ) -> Subscription:
        subscription = await self._repository.get_company_subscription(
            company_id, lock=lock
        )
        if subscription is None:
            raise BillingNotFoundError("The subscription does not exist.")
        return subscription

    def _reconcile(self, subscription: Subscription, now: datetime) -> bool:
        period_end = (
            _as_utc(subscription.current_period_end)
            if subscription.current_period_end
            else None
        )
        status_changed_at = _as_utc(subscription.status_changed_at)
        grace_ends_at = (
            _as_utc(subscription.grace_period_ends_at)
            if subscription.grace_period_ends_at
            else None
        )
        suspended_at = (
            _as_utc(subscription.suspended_at) if subscription.suspended_at else None
        )
        if (
            subscription.cancel_at_period_end
            and period_end is not None
            and period_end <= now
            and subscription.status in {"trialing", "active", "past_due"}
        ):
            self._transition(
                subscription,
                "cancelled",
                now=now,
                actor_user_id=None,
                action="subscription.period_cancelled",
            )
            subscription.ended_at = now
            return True
        if (
            subscription.status == "incomplete"
            and status_changed_at
            + timedelta(hours=self._policy.incomplete_expiry_hours)
            <= now
        ):
            self._transition(
                subscription,
                "expired",
                now=now,
                actor_user_id=None,
                action="subscription.incomplete_expired",
            )
            subscription.ended_at = now
            return True
        if (
            subscription.status == "past_due"
            and grace_ends_at is not None
            and grace_ends_at <= now
        ):
            self._transition(
                subscription,
                "suspended",
                now=now,
                actor_user_id=None,
                action="subscription.grace_expired",
            )
            subscription.suspended_at = now
            return True
        if (
            subscription.status == "suspended"
            and suspended_at is not None
            and suspended_at
            + timedelta(days=self._policy.suspension_expiry_days)
            <= now
        ):
            self._transition(
                subscription,
                "expired",
                now=now,
                actor_user_id=None,
                action="subscription.suspension_expired",
            )
            subscription.ended_at = now
            return True
        return False

    def _transition(
        self,
        subscription: Subscription,
        target: str,
        *,
        now: datetime,
        actor_user_id: UUID | None,
        action: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        previous = subscription.status
        if previous == target:
            return
        subscription.status = target
        subscription.status_changed_at = now
        subscription.version += 1
        self._audit(
            company_id=subscription.company_id,
            actor_user_id=actor_user_id,
            action=action,
            metadata={
                "subscription_id": str(subscription.id),
                "from_status": previous,
                "to_status": target,
                **(metadata or {}),
            },
        )

    def _audit(
        self,
        *,
        company_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        metadata: dict[str, object],
        result: str = "succeeded",
    ) -> None:
        self._repository.add_audit_event(
            BillingAuditEvent(
                company_id=company_id,
                actor_user_id=actor_user_id,
                action=action,
                result=result,
                safe_metadata=metadata,
            )
        )

    async def ingest_webhook(
        self, payload: dict[str, object], *, signature: str
    ) -> WebhookIngestResult:
        provider = self._require_provider()
        normalized = provider.parse_webhook(payload, signature=signature)
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await self._repository.get_event_by_provider_id(
            provider.name, normalized.provider_event_id
        )
        duplicate = existing is not None
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise BillingWebhookPayloadError(
                    "The provider event identifier was reused with different content."
                )
            event = existing
        else:
            payment = await self._repository.get_payment(normalized.payment_reference)
            event = BillingWebhookEvent(
                company_id=payment.company_id if payment is not None else None,
                provider=provider.name,
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
                    provider.name, normalized.provider_event_id
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
    "succeeded": 4,
    "cancelled": 5,
    "reversed": 6,
    "refunded": 7,
}


class BillingWebhookProcessor:
    """Transactionally apply queued normalized callbacks exactly once."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_name: str,
        *,
        policy: BillingPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._provider_name = provider_name
        self._policy = policy or BillingPolicy()

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
                prior_state = payment.status
                payment.provider_payment_id = provider_payment_id
                payment.status = state
                payment.failure_code = (
                    str(payload.get("failure_code"))[:80]
                    if payload.get("failure_code")
                    else None
                )
                payment.provider_occurred_at = occurred_at
                event.company_id = payment.company_id
                subscription = (
                    await repository.get_subscription(
                        payment.subscription_id, lock=True
                    )
                    if payment.subscription_id
                    else None
                )
                if subscription is not None:
                    await self._apply_subscription_event(
                        repository,
                        subscription,
                        payment,
                        event,
                        prior_state=prior_state,
                        now=occurred_at or datetime.now(UTC),
                    )
                event.status = "processed"
                event.last_error = None
            event.processed_at = datetime.now(UTC)
            await session.commit()

    async def _apply_subscription_event(
        self,
        repository: BillingRepository,
        subscription: Subscription,
        payment: Payment,
        event: BillingWebhookEvent,
        *,
        prior_state: str,
        now: datetime,
    ) -> None:
        metadata: dict[str, object] = {
            "subscription_id": str(subscription.id),
            "payment_id": str(payment.id),
            "provider_event_id": event.provider_event_id,
        }
        if payment.status == "succeeded":
            if (
                subscription.latest_payment_id == payment.id
                and prior_state == "succeeded"
            ):
                return
            plan = await repository.get_plan(payment.plan_code or "")
            if plan is None:
                raise BillingStateError("The paid plan no longer exists.")
            previous = subscription.status
            subscription.plan_id = plan.id
            subscription.pending_plan_id = None
            subscription.latest_payment_id = payment.id
            if payment.purpose == "renewal" and subscription.current_period_end:
                period_start = max(now, _as_utc(subscription.current_period_end))
            else:
                period_start = now
                subscription.cancel_at_period_end = False
            subscription.current_period_start = period_start
            subscription.current_period_end = _next_month(period_start)
            subscription.grace_period_ends_at = None
            subscription.suspended_at = None
            subscription.ended_at = None
            self._transition(
                repository,
                subscription,
                "active",
                now=now,
                action="subscription.payment_activated",
                metadata={**metadata, "from_status": previous, "plan_code": plan.code},
            )
            if await repository.get_invoice_for_payment(payment.id) is None:
                repository.add_invoice_reference(
                    InvoiceReference(
                        company_id=payment.company_id,
                        subscription_id=subscription.id,
                        payment_id=payment.id,
                        provider=payment.provider,
                        provider_invoice_id=f"transaction:{payment.provider_payment_id}",
                        amount_minor=payment.amount_minor,
                        currency=payment.currency,
                        status="paid",
                        issued_at=now,
                    )
                )
        elif payment.status == "failed" and payment.purpose == "renewal":
            if subscription.status in {"trialing", "active", "past_due"}:
                self._transition(
                    repository,
                    subscription,
                    "past_due",
                    now=now,
                    action="subscription.payment_failed",
                    metadata=metadata,
                )
                subscription.grace_period_ends_at = now + timedelta(
                    days=self._policy.grace_period_days
                )
        elif payment.status in {"refunded", "reversed", "cancelled"}:
            if subscription.latest_payment_id == payment.id:
                self._transition(
                    repository,
                    subscription,
                    "suspended",
                    now=now,
                    action=f"subscription.payment_{payment.status}",
                    metadata=metadata,
                )
                subscription.suspended_at = now
                subscription.grace_period_ends_at = None

    @staticmethod
    def _transition(
        repository: BillingRepository,
        subscription: Subscription,
        target: str,
        *,
        now: datetime,
        action: str,
        metadata: dict[str, object],
    ) -> None:
        previous = subscription.status
        if previous == target:
            return
        subscription.status = target
        subscription.status_changed_at = now
        subscription.version += 1
        repository.add_audit_event(
            BillingAuditEvent(
                company_id=subscription.company_id,
                actor_user_id=None,
                action=action,
                result="succeeded",
                safe_metadata={
                    **metadata,
                    "from_status": previous,
                    "to_status": target,
                },
            )
        )

    @staticmethod
    def _is_stale(payment: Payment, state: str, occurred_at: datetime | None) -> bool:
        current_rank = _STATE_RANK.get(payment.status, -1)
        incoming_rank = _STATE_RANK[state]
        if payment.status == "cancelled" and payment.provider_payment_id is None:
            current_rank = 1
        if incoming_rank < current_rank:
            return True
        return bool(
            incoming_rank == current_rank
            and occurred_at is not None
            and payment.provider_occurred_at is not None
            and occurred_at < payment.provider_occurred_at
        )

"""Hosted checkout, subscription lifecycle, and durable webhook processing."""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
import logging
import secrets
import time
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
    PaymentProviderSignatureError,
    ProviderWebhook,
)
from app.billing.queue import BillingWebhookQueue
from app.models.billing import (
    BillingAuditEvent,
    BillingPlan,
    BillingWebhookEvent,
    InvoiceReference,
    Payment,
    Subscription,
)
from app.models.user import User
from app.observability.logging import current_correlation_id, current_request_id
from app.observability.metrics import (
    record_billing_lifecycle_reconciliation,
    record_billing_webhook_ingest,
    record_billing_webhook_processing,
    record_billing_webhook_recovery,
    record_billing_webhook_replay,
)
from app.repositories.billing import BillingRepository


class BillingError(RuntimeError):
    """Base billing use-case failure with a stable public code."""

    code = "billing_error"


class BillingNotFoundError(BillingError):
    code = "billing_not_found"


class BillingConflictError(BillingError):
    code = "billing_conflict"


class CheckoutUnresolvedError(BillingConflictError):
    code = "checkout_unresolved"

    def __init__(self, payment: Payment) -> None:
        super().__init__(
            "We're still verifying your existing payment. Please don't try again yet."
        )
        self.payment_id = payment.id
        self.checkout_intent_status = payment.checkout_intent_status
        self.provider_decision = payment.provider_decision


class BillingWebhookPayloadError(BillingError):
    code = "webhook_payload_conflict"


class BillingStateError(BillingConflictError):
    code = "invalid_subscription_transition"


_WEBHOOK_INGEST_METRIC_OUTCOMES = {
    "accepted": "accepted",
    "duplicate": "duplicate_suppressed",
    "quarantined_missing_hmac": "crypto_missing_hmac",
    "quarantined_invalid_hmac": "crypto_invalid_hmac",
    "quarantined_unknown_payment": "business_unknown_payment",
    "quarantined_wrong_amount": "business_wrong_amount",
    "quarantined_wrong_currency": "business_wrong_currency",
    "quarantined_wrong_integration": "business_wrong_integration",
    "quarantined_wrong_environment": "business_wrong_environment",
    "quarantined_wrong_merchant": "business_wrong_merchant",
}


def _webhook_ingest_metric_outcome(outcome: str) -> str:
    return _WEBHOOK_INGEST_METRIC_OUTCOMES.get(outcome, "unknown")


@dataclass(frozen=True, slots=True)
class BillingPolicy:
    grace_period_days: int = 7
    incomplete_expiry_hours: int = 24
    suspension_expiry_days: int = 30
    checkout_expiry_minutes: int = 30
    return_reference_expiry_minutes: int = 60
    commercial_model: str = "prepaid_manual_renewal"
    environment: str = "legacy_unknown"
    provider_integration_id: int | None = None
    provider_merchant_id: str | None = None
    provider_source_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    target: str
    action: str
    effective_at: datetime


@dataclass(frozen=True, slots=True)
class LifecycleReconciliationSummary:
    scanned: int
    transitioned: int
    failures: int
    duration_seconds: float
    oldest_stale_age_seconds: float


@dataclass(frozen=True, slots=True)
class BillingDetails:
    first_name: str
    last_name: str
    phone_number: str
    city: str
    country: str
    street: str


_REPLAYABLE_WEBHOOK_STATES = frozenset({"failed", "dead_letter"})
_REPLAYABLE_WEBHOOK_FAILURES = frozenset(
    {
        "processing_error",
        "queue_unavailable",
        "replay_queue_failed",
        "worker_stale",
    }
)


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    payment_id: UUID
    subscription_id: UUID
    plan: PlanDefinition
    status: str
    checkout: HostedCheckout
    reused: bool
    purpose: str
    checkout_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class WebhookIngestResult:
    event_id: UUID
    duplicate: bool
    should_enqueue: bool
    outcome: str


@dataclass(frozen=True, slots=True)
class WebhookRecoverySummary:
    scanned: int
    requeued: int
    dead_lettered: int
    publication_failures: int
    queue_depth: int
    oldest_queued_age_seconds: float
    oldest_processing_age_seconds: float
    failed_count: int
    dead_letter_count: int


def _next_month(value: datetime) -> datetime:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return value.replace(
        year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _decision_for_legacy_state(state: str) -> str:
    return {
        "succeeded": "succeeded_eligible",
        "failed": "failed",
        "cancelled": "cancelled",
        "refunded": "refunded",
        "reversed": "reversed",
    }.get(state, "pending")


def subscription_lifecycle_transition(
    subscription: Subscription,
    now: datetime,
    policy: BillingPolicy,
) -> LifecycleTransition | None:
    """Return the one authoritative time transition due at ``now``."""
    now = _as_utc(now)
    period_end = (
        _as_utc(subscription.current_period_end)
        if subscription.current_period_end
        else None
    )
    grace_end = (
        _as_utc(subscription.grace_period_ends_at)
        if subscription.grace_period_ends_at
        else None
    )
    status_changed = _as_utc(subscription.status_changed_at)
    suspended_at = (
        _as_utc(subscription.suspended_at) if subscription.suspended_at else None
    )
    ended_at = _as_utc(subscription.ended_at) if subscription.ended_at else None

    if subscription.status in {"cancelled", "expired"}:
        return None
    if ended_at is not None and ended_at <= now:
        return LifecycleTransition("expired", "subscription.ended", ended_at)
    if (
        subscription.status in {"trialing", "active", "past_due"}
        and suspended_at is not None
        and suspended_at <= now
    ):
        return LifecycleTransition(
            "suspended", "subscription.suspension_effective", suspended_at
        )
    if (
        subscription.cancel_at_period_end
        and period_end is not None
        and period_end <= now
        and subscription.status in {"trialing", "active", "past_due"}
    ):
        return LifecycleTransition(
            "cancelled", "subscription.period_cancelled", period_end
        )
    if subscription.status == "incomplete":
        due = status_changed + timedelta(hours=policy.incomplete_expiry_hours)
        return (
            LifecycleTransition("expired", "subscription.incomplete_expired", due)
            if due <= now
            else None
        )
    if subscription.status == "past_due":
        if grace_end is None or grace_end <= now:
            return LifecycleTransition(
                "suspended",
                "subscription.grace_expired",
                grace_end or status_changed,
            )
        return None
    if subscription.status in {"trialing", "active"}:
        if period_end is None or period_end <= now:
            return LifecycleTransition(
                "expired",
                "subscription.period_expired",
                period_end or status_changed,
            )
        return None
    if subscription.status == "suspended" and suspended_at is not None:
        due = suspended_at + timedelta(days=policy.suspension_expiry_days)
        if due <= now:
            return LifecycleTransition(
                "expired", "subscription.suspension_expired", due
            )
    return None


def effective_subscription_status(
    subscription: Subscription,
    *,
    now: datetime,
    policy: BillingPolicy | None = None,
) -> str:
    """Evaluate access from status and timestamps without trusting stale storage."""
    transition = subscription_lifecycle_transition(
        subscription, now, policy or BillingPolicy()
    )
    return transition.target if transition is not None else subscription.status


logger = logging.getLogger(__name__)
_lifecycle_reconciliation_lock = asyncio.Lock()


class SubscriptionLifecycleReconciler:
    """Run bounded, idempotent lifecycle transitions independent of page reads."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: BillingPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy or BillingPolicy()

    async def run(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> LifecycleReconciliationSummary:
        async with _lifecycle_reconciliation_lock:
            return await self._run_locked(limit=limit, now=now)

    async def _run_locked(
        self,
        *,
        limit: int,
        now: datetime | None,
    ) -> LifecycleReconciliationSummary:
        started = time.monotonic()
        effective_now = _as_utc(now or datetime.now(UTC))
        transitioned = 0
        failures = 0
        oldest_age = 0.0
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            subscriptions = await repository.list_lifecycle_subscriptions(
                now=effective_now,
                incomplete_before=effective_now
                - timedelta(hours=self._policy.incomplete_expiry_hours),
                suspended_before=effective_now
                - timedelta(days=self._policy.suspension_expiry_days),
                limit=limit,
            )
            for subscription in subscriptions:
                transition = subscription_lifecycle_transition(
                    subscription, effective_now, self._policy
                )
                if transition is None:
                    continue
                oldest_age = max(
                    oldest_age,
                    max(
                        0.0,
                        (effective_now - transition.effective_at).total_seconds(),
                    ),
                )
                subscription_id = subscription.id
                try:
                    async with session.begin_nested():
                        changed = await repository.transition_subscription_if_current(
                            subscription=subscription,
                            target=transition.target,
                            now=effective_now,
                            suspended_at=(
                                effective_now
                                if transition.target == "suspended"
                                else subscription.suspended_at
                            ),
                            ended_at=(
                                effective_now
                                if transition.target in {"cancelled", "expired"}
                                else subscription.ended_at
                            ),
                        )
                        if changed:
                            repository.add_audit_event(
                                BillingAuditEvent(
                                    company_id=subscription.company_id,
                                    actor_user_id=None,
                                    action=transition.action,
                                    result="succeeded",
                                    safe_metadata={
                                        "subscription_id": str(subscription.id),
                                        "from_status": subscription.status,
                                        "to_status": transition.target,
                                        "trigger": "scheduled_reconciliation",
                                    },
                                )
                            )
                            transitioned += 1
                except Exception:
                    failures += 1
                    logger.exception(
                        "billing_lifecycle_transition_failed",
                        extra={"subscription_id": str(subscription_id)},
                    )
            await session.commit()
        duration = max(0.0, time.monotonic() - started)
        logger.info(
            "billing_lifecycle_reconciled",
            extra={
                "scanned": len(subscriptions),
                "transitioned": transitioned,
                "failures": failures,
                "duration_seconds": duration,
                "oldest_stale_age_seconds": oldest_age,
            },
        )
        record_billing_lifecycle_reconciliation(
            scanned=len(subscriptions),
            transitioned=transitioned,
            failures=failures,
            duration_seconds=duration,
            oldest_stale_age_seconds=oldest_age,
        )
        return LifecycleReconciliationSummary(
            scanned=len(subscriptions),
            transitioned=transitioned,
            failures=failures,
            duration_seconds=duration,
            oldest_stale_age_seconds=oldest_age,
        )


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
        if not await self._repository.company_is_billable(actor.company_id, lock=True):
            raise BillingNotFoundError("The billing company does not exist.")

        created_here = False
        existing = await self._repository.get_by_idempotency(
            actor.company_id, idempotency_key
        )
        return_reference: str | None = None
        if existing is None:
            unresolved = await self._repository.list_unresolved_company_payments(
                actor.company_id, lock=True
            )
            if unresolved:
                raise CheckoutUnresolvedError(unresolved[0])
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
                current_definition = get_plan(current_plan.code)
                if current_definition is None:
                    raise BillingStateError(
                        "The current subscription plan is disabled or invalid."
                    )
                if expected_change == "upgrade" and (
                    plan.monthly_price_minor <= current_definition.monthly_price_minor
                ):
                    raise BillingStateError("The requested plan is not an upgrade.")
                if expected_change == "downgrade" and (
                    plan.monthly_price_minor >= current_definition.monthly_price_minor
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

            payment_id = uuid4()
            return_reference = self.generate_return_reference()
            checkout_expires_at = now + timedelta(
                minutes=self._policy.checkout_expiry_minutes
            )
            payment = Payment(
                id=payment_id,
                company_id=actor.company_id,
                subscription_id=subscription.id,
                provider=provider.name,
                idempotency_key=idempotency_key,
                plan_code=plan.code,
                purpose=purpose,
                amount_minor=plan.monthly_price_minor,
                currency=plan.currency,
                status="creating",
                checkout_intent_status="open",
                checkout_expires_at=checkout_expires_at,
                return_reference_hash=self.hash_return_reference(return_reference),
                return_reference_expires_at=now
                + timedelta(minutes=self._policy.return_reference_expiry_minutes),
                return_reference_purpose="checkout_return",
                environment=self._policy.environment,
                commercial_model=self._policy.commercial_model,
                provider_decision="pending",
                provider_integration_id=self._policy.provider_integration_id,
                provider_merchant_id=self._policy.provider_merchant_id,
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
            except IntegrityError as exc:
                await self._session.rollback()
                existing = await self._repository.get_by_idempotency(
                    actor.company_id, idempotency_key
                )
                if existing is None:
                    unresolved = (
                        await self._repository.list_unresolved_company_payments(
                            actor.company_id, lock=True
                        )
                    )
                    if unresolved:
                        raise CheckoutUnresolvedError(unresolved[0]) from exc
                    raise BillingConflictError(
                        "Checkout creation conflicted with another request."
                    ) from exc
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
            if not self._checkout_is_open(payment, datetime.now(UTC)):
                raise BillingConflictError("This hosted checkout has expired.")
            return self._checkout_result(payment, plan, reused=True)
        if payment.status == "provider_error":
            raise CheckoutUnresolvedError(payment)
        if payment.status == "creating" and not created_here:
            raise BillingConflictError("Checkout creation is already in progress.")
        if payment.status != "creating":
            raise BillingConflictError(
                "This payment can no longer create a hosted checkout."
            )
        try:
            assert return_reference is not None
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
                    return_reference=return_reference,
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
        locked_payment = await self._repository.get_payment(payment.id, lock=True)
        if locked_payment is None:
            raise BillingNotFoundError("The checkout payment no longer exists.")
        locked_payment.provider_checkout_id = checkout.provider_checkout_id
        locked_payment.provider_order_id = checkout.provider_order_id
        locked_payment.checkout_url = checkout.checkout_url
        locked_payment.status = "pending"
        locked_payment.failure_code = None
        if locked_payment.checkout_intent_status != "open":
            self._audit(
                company_id=locked_payment.company_id,
                actor_user_id=actor.id,
                action="checkout.created_after_supersession",
                result="failed",
                metadata={"payment_id": str(locked_payment.id)},
            )
            await self._session.commit()
            raise BillingConflictError(
                "This checkout was superseded by a newer request."
            )
        self._audit(
            company_id=locked_payment.company_id,
            actor_user_id=actor.id,
            action="checkout.created",
            metadata={
                "payment_id": str(locked_payment.id),
                "provider_checkout_id": checkout.provider_checkout_id,
            },
        )
        await self._session.commit()
        payment = locked_payment
        assert payment.subscription_id is not None
        return CheckoutResult(
            payment_id=payment.id,
            subscription_id=payment.subscription_id,
            plan=plan,
            status=payment.status,
            checkout=checkout,
            reused=False,
            purpose=payment.purpose,
            checkout_expires_at=payment.checkout_expires_at,
        )

    async def _ensure_plan(self, plan: PlanDefinition) -> BillingPlan:
        record = await self._repository.get_plan_record(plan.code)
        if record is not None:
            if not record.is_active:
                raise BillingNotFoundError(
                    "The requested billing plan is currently disabled."
                )
            if (
                record.name != plan.name
                or record.currency != plan.currency
                or record.monthly_price_minor != plan.monthly_price_minor
            ):
                raise BillingStateError(
                    "The persisted billing plan does not match the server catalogue."
                )
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
    def generate_return_reference() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_return_reference(reference: str) -> str:
        return hashlib.sha256(reference.encode("utf-8")).hexdigest()

    @staticmethod
    def _checkout_is_open(payment: Payment, now: datetime) -> bool:
        expires_at = payment.checkout_expires_at
        return (
            payment.checkout_intent_status == "open"
            and expires_at is not None
            and _as_utc(expires_at) > now
        )

    @staticmethod
    def _checkout_has_expired(payment: Payment, now: datetime) -> bool:
        return bool(
            payment.checkout_expires_at is not None
            and _as_utc(payment.checkout_expires_at) <= now
        )

    @staticmethod
    def _expire_checkout(payment: Payment) -> None:
        payment.checkout_intent_status = "expired"

    async def payment_status(self, *, actor: User, payment_id: UUID) -> Payment:
        payment = await self._repository.get_company_payment(
            payment_id, actor.company_id, lock=True
        )
        if payment is None:
            raise BillingNotFoundError("The payment does not exist.")
        if payment.checkout_intent_status == "open" and self._checkout_has_expired(
            payment, datetime.now(UTC)
        ):
            self._expire_checkout(payment)
            await self._session.commit()
        return payment

    async def resolve_return_reference(
        self, *, company_id: UUID, reference: str
    ) -> Payment:
        payment = await self._repository.get_company_payment_by_return_hash(
            company_id, self.hash_return_reference(reference)
        )
        if payment is None:
            raise BillingNotFoundError("The payment return reference is invalid.")
        expires_at = payment.return_reference_expires_at
        if expires_at is None or _as_utc(expires_at) <= datetime.now(UTC):
            raise BillingNotFoundError("The payment return reference has expired.")
        if payment.checkout_intent_status == "open" and self._checkout_has_expired(
            payment, datetime.now(UTC)
        ):
            self._expire_checkout(payment)
            await self._session.commit()
        return payment

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
                provider_order_id=payment.provider_order_id,
            ),
            reused=reused,
            purpose=payment.purpose,
            checkout_expires_at=payment.checkout_expires_at,
        )

    async def cancel_checkout(self, *, actor: User, payment_id: UUID) -> Payment:
        payment = await self._repository.get_company_payment(
            payment_id, actor.company_id, lock=True
        )
        if payment is None:
            raise BillingNotFoundError("The payment does not exist.")
        if payment.status in {"creating", "pending", "provider_error"}:
            payment.checkout_intent_status = "cancelled"
            payment.failure_code = None
            self._audit(
                company_id=actor.company_id,
                actor_user_id=actor.id,
                action="checkout.cancelled",
                metadata={
                    "payment_id": str(payment.id),
                    "provider_confirmation": "pending",
                },
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
                    "effective_at": (
                        subscription.current_period_end.isoformat()
                        if subscription.current_period_end
                        else None
                    ),
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
        transition = subscription_lifecycle_transition(subscription, now, self._policy)
        if transition is None:
            return False
        self._transition(
            subscription,
            transition.target,
            now=now,
            actor_user_id=None,
            action=transition.action,
        )
        if transition.target == "suspended":
            subscription.suspended_at = now
        if transition.target in {"cancelled", "expired"}:
            subscription.ended_at = now
            subscription.cancel_at_period_end = False
        return True

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
        self, payload: dict[str, object], *, signature: str | None
    ) -> WebhookIngestResult:
        provider = self._require_provider()
        record_billing_webhook_ingest(outcome="received")
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if not signature:
            return await self._quarantine_signature_failure(
                provider_name=provider.name,
                payload_hash=payload_hash,
                category="quarantined_missing_hmac",
            )
        try:
            normalized = provider.parse_webhook(payload, signature=signature)
        except PaymentProviderSignatureError:
            return await self._quarantine_signature_failure(
                provider_name=provider.name,
                payload_hash=payload_hash,
                category="quarantined_invalid_hmac",
            )
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
            validation_outcome = normalized.validation_outcome
            if payment is None or payment.provider != provider.name:
                validation_outcome = "quarantined_unknown_payment"
            elif payment.amount_minor != normalized.amount_minor:
                validation_outcome = "quarantined_wrong_amount"
            elif payment.currency != normalized.currency:
                validation_outcome = "quarantined_wrong_currency"
            elif (
                payment.provider_integration_id is not None
                and payment.provider_integration_id != normalized.integration_id
            ):
                validation_outcome = "quarantined_wrong_integration"
            elif (
                payment.environment != "legacy_unknown"
                and payment.environment != normalized.environment
            ):
                validation_outcome = "quarantined_wrong_environment"
            elif (
                payment.provider_merchant_id is not None
                and payment.provider_merchant_id != normalized.merchant_id
            ):
                validation_outcome = "quarantined_wrong_merchant"
            quarantined = validation_outcome != "accepted"
            safe_payload = self._safe_payload(normalized)
            safe_payload["validation_outcome"] = validation_outcome
            event = BillingWebhookEvent(
                company_id=payment.company_id if payment is not None else None,
                provider=provider.name,
                provider_event_id=normalized.provider_event_id,
                raw_provider_event_id=normalized.raw_provider_event_id,
                event_type=normalized.event_type,
                payload_hash=payload_hash,
                safe_payload=safe_payload,
                validation_outcome=validation_outcome,
                status="quarantined" if quarantined else "received",
                last_error_category=validation_outcome if quarantined else None,
                last_error=validation_outcome if quarantined else None,
                processed_at=datetime.now(UTC) if quarantined else None,
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
        should_enqueue = (
            await self._repository.claim_event_for_enqueue(event.id)
            if event.validation_outcome == "accepted"
            else False
        )
        await self._session.commit()
        result = WebhookIngestResult(
            event_id=event.id,
            duplicate=duplicate,
            should_enqueue=should_enqueue,
            outcome="duplicate" if duplicate else event.validation_outcome,
        )
        record_billing_webhook_ingest(
            outcome=_webhook_ingest_metric_outcome(result.outcome)
        )
        return result

    async def _quarantine_signature_failure(
        self,
        *,
        provider_name: str,
        payload_hash: str,
        category: Literal["quarantined_missing_hmac", "quarantined_invalid_hmac"],
    ) -> WebhookIngestResult:
        provider_event_id = f"{category}:{payload_hash[:40]}"
        existing = await self._repository.get_event_by_provider_id(
            provider_name, provider_event_id
        )
        if existing is None:
            event = BillingWebhookEvent(
                provider=provider_name,
                provider_event_id=provider_event_id,
                event_type=f"transaction.{category.removeprefix('quarantined_')}",
                payload_hash=payload_hash,
                safe_payload={"validation_outcome": category},
                validation_outcome=category,
                status="quarantined",
                last_error_category=category,
                last_error=category,
                processed_at=datetime.now(UTC),
            )
            self._repository.add_event(event)
            await self._session.commit()
            result = WebhookIngestResult(
                event_id=event.id,
                duplicate=False,
                should_enqueue=False,
                outcome=category,
            )
        else:
            result = WebhookIngestResult(
                event_id=existing.id,
                duplicate=True,
                should_enqueue=False,
                outcome="duplicate",
            )
        record_billing_webhook_ingest(
            outcome=_webhook_ingest_metric_outcome(result.outcome)
        )
        return result

    async def release_failed_enqueue(
        self,
        event_id: UUID,
        *,
        category: str = "queue_unavailable",
    ) -> None:
        await self._repository.release_event_enqueue(
            event_id,
            category=category,
            message="Webhook publication failed and will be retried.",
            next_retry_at=datetime.now(UTC) + timedelta(seconds=30),
        )
        await self._session.commit()

    async def replay_webhook_event(
        self,
        *,
        actor: User,
        company_id: UUID,
        event_id: UUID,
        reason: str,
    ) -> BillingWebhookEvent:
        if not actor.is_platform_operator:
            raise BillingConflictError(
                "Platform-operator authorization is required for webhook replay."
            )
        event = await self._repository.get_company_event(
            event_id, company_id, lock=True
        )
        if event is None:
            raise BillingNotFoundError("The provider event does not exist.")
        previous_status = event.status
        previous_error_category = event.last_error_category
        rejection_reason: str | None = None
        if event.validation_outcome != "accepted":
            rejection_reason = "validation_not_accepted"
        elif event.safe_payload is None or (
            event.safe_payload.get("validation_outcome") != "accepted"
        ):
            rejection_reason = "validation_evidence_missing"
        elif event.status not in _REPLAYABLE_WEBHOOK_STATES:
            rejection_reason = "state_not_replayable"
        elif event.processed_at is not None:
            rejection_reason = "already_completed"
        elif event.last_error_category not in _REPLAYABLE_WEBHOOK_FAILURES:
            rejection_reason = "failure_not_recoverable"
        if rejection_reason is not None:
            self._audit(
                company_id=company_id,
                actor_user_id=actor.id,
                action="webhook.replay_rejected",
                result="failed",
                metadata={
                    "event_id": str(event.id),
                    "provider": event.provider,
                    "previous_status": previous_status,
                    "resulting_status": previous_status,
                    "previous_error_category": previous_error_category,
                    "replay_eligibility": "rejected",
                    "rejection_reason": rejection_reason,
                    "reason": reason,
                    "request_id": current_request_id(),
                    "correlation_id": current_correlation_id(),
                },
            )
            await self._session.commit()
            raise BillingConflictError(
                "The provider event is not eligible for operational replay."
            )

        queued_at = datetime.now(UTC)
        replay_count = event.replay_count
        event_provider = event.provider
        actor_id = actor.id
        queued = await self._repository.queue_event_for_replay(
            event.id,
            company_id,
            previous_status=previous_status,
            previous_error_category=previous_error_category,
            replay_count=replay_count,
            now=queued_at,
        )
        if not queued:
            await self._session.rollback()
            self._audit(
                company_id=company_id,
                actor_user_id=actor_id,
                action="webhook.replay_rejected",
                result="failed",
                metadata={
                    "event_id": str(event_id),
                    "provider": event_provider,
                    "previous_status": previous_status,
                    "resulting_status": "concurrent_change",
                    "previous_error_category": previous_error_category,
                    "replay_eligibility": "rejected",
                    "rejection_reason": "concurrent_change",
                    "reason": reason,
                    "request_id": current_request_id(),
                    "correlation_id": current_correlation_id(),
                },
            )
            await self._session.commit()
            raise BillingConflictError(
                "The provider event changed while replay was being requested."
            )
        await self._session.refresh(event)
        self._audit(
            company_id=company_id,
            actor_user_id=actor.id,
            action="webhook.safe_replay",
            metadata={
                "event_id": str(event.id),
                "provider": event.provider,
                "previous_status": previous_status,
                "resulting_status": event.status,
                "previous_error_category": previous_error_category,
                "replay_count": event.replay_count,
                "replay_eligibility": "accepted",
                "reason": reason,
                "request_id": current_request_id(),
                "correlation_id": current_correlation_id(),
            },
        )
        await self._session.commit()
        record_billing_webhook_replay()
        return event

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
            "decision": event.decision or _decision_for_legacy_state(event.state),
            "validation_outcome": event.validation_outcome,
            "integration_id": event.integration_id,
            "environment": event.environment,
            "merchant_id": event.merchant_id,
            "provider_order_id": event.provider_order_id,
            "source_type": event.source_type,
        }


class BillingWebhookRecoveryService:
    """Reclaim durable webhook work and expose bounded operational state."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: BillingWebhookQueue,
        *,
        max_attempts: int,
        retry_base_seconds: float,
        queued_stale_seconds: int,
        processing_stale_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._queued_stale_seconds = queued_stale_seconds
        self._processing_stale_seconds = processing_stale_seconds

    async def run(
        self, *, limit: int, now: datetime | None = None
    ) -> WebhookRecoverySummary:
        effective_now = _as_utc(now or datetime.now(UTC))
        queued_before = effective_now - timedelta(seconds=self._queued_stale_seconds)
        processing_before = effective_now - timedelta(
            seconds=self._processing_stale_seconds
        )
        queued_ids: list[UUID] = []
        dead_lettered = 0
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            events = await repository.list_recoverable_events(
                now=effective_now,
                queued_before=queued_before,
                processing_before=processing_before,
                limit=limit,
            )
            for event in events:
                if (
                    event.status == "processing"
                    and event.attempts >= self._max_attempts
                ):
                    event.status = "dead_letter"
                    event.processing_started_at = None
                    event.next_retry_at = None
                    event.dead_lettered_at = effective_now
                    event.last_error_category = "worker_stale"
                    event.last_error = "The worker lease expired after the retry limit."
                    dead_lettered += 1
                    continue
                if event.status == "processing":
                    event.last_error_category = "worker_stale"
                    event.last_error = "The worker lease expired and was reclaimed."
                event.status = "queued"
                event.queued_at = effective_now
                event.processing_started_at = None
                event.next_retry_at = None
                queued_ids.append(event.id)
            await session.commit()

        publication_failures = 0
        for event_id in queued_ids:
            try:
                self._queue.enqueue(event_id)
            except Exception:
                publication_failures += 1
                async with self._session_factory() as session:
                    await BillingRepository(session).release_event_enqueue(
                        event_id,
                        category="queue_unavailable",
                        message="Webhook publication failed and will be retried.",
                        next_retry_at=effective_now
                        + timedelta(seconds=self._retry_base_seconds),
                    )
                    await session.commit()

        async with self._session_factory() as session:
            repository = BillingRepository(session)
            stats = await repository.webhook_operational_stats(now=effective_now)
            state_ages = await repository.billing_state_ages(now=effective_now)
        logger.info(
            "billing_webhook_recovery_completed",
            extra={
                "scanned": len(events),
                "requeued": len(queued_ids) - publication_failures,
                "dead_lettered": dead_lettered,
                "publication_failures": publication_failures,
                "queue_depth": stats[0],
                "oldest_queued_age_seconds": stats[1],
                "oldest_processing_age_seconds": stats[2],
                "failed_count": stats[3],
                "dead_letter_count": stats[4],
            },
        )
        record_billing_webhook_recovery(
            queue_depth=stats[0],
            oldest_queued_age_seconds=stats[1],
            oldest_processing_age_seconds=stats[2],
            failed_count=stats[3],
            dead_letter_count=stats[4],
            oldest_pending_payment_age_seconds=state_ages[0],
            oldest_incomplete_subscription_age_seconds=state_ages[1],
        )
        return WebhookRecoverySummary(
            scanned=len(events),
            requeued=len(queued_ids) - publication_failures,
            dead_lettered=dead_lettered,
            publication_failures=publication_failures,
            queue_depth=stats[0],
            oldest_queued_age_seconds=stats[1],
            oldest_processing_age_seconds=stats[2],
            failed_count=stats[3],
            dead_letter_count=stats[4],
        )


_DECISION_RANK = {
    "pending": 1,
    "authorized_not_captured": 2,
    "failed": 2,
    "under_review": 3,
    "succeeded_eligible": 4,
    "cancelled": 5,
    "reversed": 6,
    "refunded": 7,
    "expired": 1,
    "quarantined": 8,
}


class BillingWebhookProcessor:
    """Transactionally apply queued normalized callbacks exactly once."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_name: str,
        *,
        policy: BillingPolicy | None = None,
        max_attempts: int = 5,
        retry_base_seconds: float = 30.0,
    ) -> None:
        self._session_factory = session_factory
        self._provider_name = provider_name
        self._policy = policy or BillingPolicy()
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds

    async def execute(self, event_id: UUID) -> None:
        claimed_at = datetime.now(UTC)
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            claimed = await repository.claim_event_for_processing(
                event_id, now=claimed_at
            )
            await session.commit()
        if not claimed:
            return

        try:
            await self._process_claimed_event(event_id)
        except Exception as exc:
            await self._record_processing_failure(event_id, exc)
        await self._record_processing_observation(event_id)

    async def _record_processing_observation(self, event_id: UUID) -> None:
        try:
            async with self._session_factory() as session:
                event = await BillingRepository(session).get_event(event_id)
        except Exception:
            logger.warning("billing_webhook_processing_metric_unavailable")
            return
        if event is None:
            return
        outcome = {
            "processed": "processed",
            "quarantined": "quarantined",
            "failed": "retry_scheduled",
            "dead_letter": "dead_letter",
        }.get(event.status)
        if outcome is None:
            return
        record_billing_webhook_processing(
            outcome=outcome,
            latency_seconds=max(
                0.0,
                (datetime.now(UTC) - _as_utc(event.received_at)).total_seconds(),
            ),
        )

    async def _process_claimed_event(self, event_id: UUID) -> None:
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            event = await repository.get_event(event_id, lock=True)
            if event is None or event.status != "processing":
                return
            payload = event.safe_payload or {}
            if event.validation_outcome != "accepted":
                self._quarantine_processing(
                    repository, event, "validation_not_accepted"
                )
                await session.commit()
                return
            if payload.get("validation_outcome") != "accepted":
                self._quarantine_processing(
                    repository, event, "validation_evidence_missing"
                )
                await session.commit()
                return
            if event.provider != self._provider_name or event.company_id is None:
                self._quarantine_processing(
                    repository, event, "provider_tenant_mismatch"
                )
                await session.commit()
                return
            reconciliation_compensation = (
                event.event_type == "reconciliation.compensating"
            )
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
                integration_value = payload.get("integration_id")
                integration_id = (
                    int(integration_value)
                    if isinstance(integration_value, (int, str))
                    and not isinstance(integration_value, bool)
                    else None
                )
                environment_value = payload.get("environment")
                environment = (
                    str(environment_value) if environment_value is not None else None
                )
                merchant_value = payload.get("merchant_id")
                merchant_id = (
                    str(merchant_value) if merchant_value is not None else None
                )
                source_value = payload.get("source_type")
                source_type = (
                    str(source_value).lower() if source_value is not None else None
                )
                provider_order_value = payload.get("provider_order_id")
                provider_order_id = (
                    str(provider_order_value)
                    if provider_order_value is not None
                    else None
                )
                decision = str(
                    payload.get("decision") or _decision_for_legacy_state(state)
                )
                occurred_value = payload.get("occurred_at")
                parsed_occurred_at = (
                    datetime.fromisoformat(str(occurred_value))
                    if occurred_value
                    else None
                )
                occurred_at = (
                    _as_utc(parsed_occurred_at)
                    if parsed_occurred_at is not None
                    and parsed_occurred_at.tzinfo is not None
                    else None
                )
                timestamp_confidence_value = payload.get(
                    "provider_timestamp_confidence"
                )
                timestamp_confidence = (
                    str(timestamp_confidence_value)
                    if timestamp_confidence_value is not None
                    else "explicit" if occurred_at is not None else "ambiguous"
                )
                temporal_source_value = payload.get("temporal_source")
                temporal_source = (
                    str(temporal_source_value)
                    if temporal_source_value is not None
                    else (
                        "provider_offset_timestamp"
                        if occurred_at is not None
                        else "webhook_received_at"
                    )
                )
                temporal_observed_value = payload.get("temporal_observed_at")
                parsed_temporal_observed_at = (
                    datetime.fromisoformat(str(temporal_observed_value))
                    if temporal_observed_value
                    else None
                )
                temporal_observed_at = (
                    _as_utc(parsed_temporal_observed_at)
                    if parsed_temporal_observed_at is not None
                    and parsed_temporal_observed_at.tzinfo is not None
                    else None
                )
                historical_owner_snapshot_mismatch = payload.get(
                    "historical_owner_snapshot_mismatch"
                )
                current_owner_binding_verified = payload.get(
                    "current_owner_binding_verified"
                )
                owner_binding_source = payload.get("owner_binding_source")
                historical_snapshot_preserved = payload.get(
                    "historical_snapshot_preserved"
                )
                if timestamp_confidence not in {"explicit", "ambiguous"}:
                    raise ValueError("Invalid timestamp confidence")
                if temporal_source not in {
                    "webhook_received_at",
                    "reconciliation_observed_at",
                    "provider_offset_timestamp",
                }:
                    raise ValueError("Invalid temporal source")
                if timestamp_confidence == "explicit" and occurred_at is None:
                    raise ValueError("Explicit provider timestamp missing")
                if timestamp_confidence == "ambiguous" and occurred_at is not None:
                    raise ValueError("Ambiguous provider timestamp has an offset")
                if temporal_source == "provider_offset_timestamp":
                    if occurred_at is None:
                        raise ValueError("Provider timestamp unavailable")
                    temporal_observed_at = occurred_at
                elif temporal_observed_at is None:
                    if event.event_type == "reconciliation.compensating":
                        raise ValueError("Trusted local observation time missing")
                    temporal_observed_at = _as_utc(event.received_at)
                if reconciliation_compensation and (
                    not isinstance(historical_owner_snapshot_mismatch, bool)
                    or current_owner_binding_verified is not True
                    or owner_binding_source != "current_configuration"
                    or historical_snapshot_preserved is not True
                ):
                    raise ValueError("Current owner binding evidence missing")
            except (KeyError, TypeError, ValueError):
                self._quarantine_processing(
                    repository, event, "invalid_normalized_payload"
                )
                await session.commit()
                return
            payment = await repository.get_payment(reference, lock=True)
            rejection_reason: str | None = None
            if payment is None:
                rejection_reason = "payment_not_found"
            elif payment.provider != self._provider_name:
                rejection_reason = "provider_mismatch"
            elif event.company_id != payment.company_id:
                rejection_reason = "tenant_mismatch"
            elif payment.amount_minor != amount_minor:
                rejection_reason = "amount_mismatch"
            elif payment.currency != currency:
                rejection_reason = "currency_mismatch"
            elif (
                payment.provider_integration_id is not None
                and payment.provider_integration_id != integration_id
            ):
                rejection_reason = "integration_mismatch"
            elif self._policy.provider_integration_id is not None and (
                self._policy.provider_integration_id != integration_id
                or payment.provider_integration_id
                != self._policy.provider_integration_id
            ):
                rejection_reason = "configured_integration_mismatch"
            elif (
                payment.environment != "legacy_unknown"
                and payment.environment != environment
            ):
                rejection_reason = "environment_mismatch"
            elif self._policy.environment != "legacy_unknown" and (
                self._policy.environment != environment
                or payment.environment != self._policy.environment
            ):
                rejection_reason = "configured_environment_mismatch"
            elif reconciliation_compensation:
                configured_owner = self._policy.provider_merchant_id
                expected_historical_mismatch = bool(
                    configured_owner is not None
                    and payment.provider_merchant_id is not None
                    and payment.provider_merchant_id != configured_owner
                )
                if configured_owner is None:
                    rejection_reason = "configured_merchant_missing"
                elif configured_owner != merchant_id:
                    rejection_reason = "configured_merchant_mismatch"
                elif historical_owner_snapshot_mismatch != expected_historical_mismatch:
                    rejection_reason = "owner_binding_evidence_mismatch"
            elif (
                payment.provider_merchant_id is not None
                and payment.provider_merchant_id != merchant_id
            ):
                rejection_reason = "merchant_mismatch"
            elif self._policy.provider_merchant_id is not None and (
                self._policy.provider_merchant_id != merchant_id
                or payment.provider_merchant_id != self._policy.provider_merchant_id
            ):
                rejection_reason = "configured_merchant_mismatch"
            elif (
                payment.provider_order_id is not None
                and payment.provider_order_id != provider_order_id
            ):
                rejection_reason = "provider_order_mismatch"
            elif (
                payment.provider_integration_id is not None
                or payment.environment != "legacy_unknown"
            ) and source_type is None:
                rejection_reason = "source_missing"
            elif self._policy.provider_source_types and (
                source_type not in self._policy.provider_source_types
            ):
                rejection_reason = "source_mismatch"
            elif decision not in _DECISION_RANK:
                rejection_reason = "unknown_state"
            elif self._is_stale(payment, decision, occurred_at):
                rejection_reason = "out_of_order"
            if rejection_reason is not None:
                self._quarantine_processing(repository, event, rejection_reason)
            else:
                assert payment is not None
                prior_state = payment.status
                payment.provider_payment_id = provider_payment_id
                payment.provider_decision = decision
                payment.provider_order_id = (
                    provider_order_id or payment.provider_order_id
                )
                payment.failure_code = (
                    str(payload.get("failure_code"))[:80]
                    if payload.get("failure_code")
                    else None
                )
                payment.provider_occurred_at = occurred_at
                event.company_id = payment.company_id
                event_time = temporal_observed_at or _as_utc(event.received_at)
                expired_before_payment = bool(
                    payment.checkout_expires_at is not None
                    and _as_utc(payment.checkout_expires_at) < event_time
                )
                delayed_provider_confirmation = bool(
                    event.event_type == "reconciliation.compensating"
                    and decision == "succeeded_eligible"
                    and timestamp_confidence == "ambiguous"
                    and temporal_source == "reconciliation_observed_at"
                )
                if decision == "succeeded_eligible" and (
                    payment.checkout_intent_status == "superseded"
                    or (expired_before_payment and not delayed_provider_confirmation)
                ):
                    if (
                        expired_before_payment
                        and payment.checkout_intent_status == "open"
                    ):
                        payment.checkout_intent_status = "expired"
                    event.status = "quarantined"
                    event.last_error_category = "superseded_or_expired_checkout_paid"
                    event.last_error = "manual_review_required"
                    repository.add_audit_event(
                        BillingAuditEvent(
                            company_id=payment.company_id,
                            actor_user_id=None,
                            action="checkout.paid_manual_review",
                            result="failed",
                            safe_metadata={
                                "payment_id": str(payment.id),
                                "event_id": str(event.id),
                                "checkout_intent_status": (
                                    payment.checkout_intent_status
                                ),
                                "temporal_source": temporal_source,
                                "provider_timestamp_confidence": (timestamp_confidence),
                            },
                        )
                    )
                    event.processed_at = event.processed_at or datetime.now(UTC)
                    event.processing_started_at = None
                    event.next_retry_at = None
                    await session.commit()
                    return
                payment.status = {
                    "succeeded_eligible": "succeeded",
                    "failed": "failed",
                    "cancelled": "cancelled",
                    "expired": "cancelled",
                    "refunded": "refunded",
                    "reversed": "reversed",
                }.get(decision, "pending")
                if decision == "succeeded_eligible":
                    payment.checkout_intent_status = "completed"
                elif decision == "failed" and payment.checkout_intent_status == "open":
                    payment.checkout_intent_status = "failed"
                elif (
                    decision == "cancelled" and payment.checkout_intent_status == "open"
                ):
                    payment.checkout_intent_status = "cancelled"
                elif decision == "expired" and payment.checkout_intent_status == "open":
                    payment.checkout_intent_status = "expired"
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
                        now=event_time,
                    )
                event.status = "processed"
                event.last_error = None
                event.last_error_category = None
            event.processed_at = event.processed_at or datetime.now(UTC)
            event.processing_started_at = None
            event.next_retry_at = None
            await session.commit()

    @staticmethod
    def _quarantine_processing(
        repository: BillingRepository,
        event: BillingWebhookEvent,
        reason: str,
    ) -> None:
        """Move an unsafe callback to a durable terminal state without payload logs."""
        event.status = "quarantined"
        event.last_error_category = reason[:64]
        event.last_error = reason[:64]
        event.processed_at = event.processed_at or datetime.now(UTC)
        event.processing_started_at = None
        event.next_retry_at = None
        if event.company_id is not None:
            repository.add_audit_event(
                BillingAuditEvent(
                    company_id=event.company_id,
                    actor_user_id=None,
                    action="webhook.processing_rejected",
                    result="failed",
                    safe_metadata={
                        "event_id": str(event.id),
                        "provider": event.provider,
                        "rejection_reason": reason[:64],
                    },
                )
            )

    async def _record_processing_failure(self, event_id: UUID, exc: Exception) -> None:
        category = (
            "billing_state_error"
            if isinstance(exc, BillingError)
            else "processing_error"
        )
        message = (
            "Billing state validation failed."
            if isinstance(exc, BillingError)
            else "Webhook processing failed and will be retried."
        )
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            event = await repository.get_event(event_id, lock=True)
            if event is None or event.status != "processing":
                return
            event.processing_started_at = None
            event.last_error_category = category
            event.last_error = message
            if event.attempts >= self._max_attempts:
                event.status = "dead_letter"
                event.next_retry_at = None
                event.dead_lettered_at = now
                if event.company_id is not None:
                    repository.add_audit_event(
                        BillingAuditEvent(
                            company_id=event.company_id,
                            actor_user_id=None,
                            action="webhook.dead_lettered",
                            result="failed",
                            safe_metadata={
                                "event_id": str(event.id),
                                "provider": event.provider,
                                "attempts": event.attempts,
                                "error_category": category,
                            },
                        )
                    )
            else:
                event.status = "failed"
                delay = min(
                    3600.0,
                    self._retry_base_seconds * (2 ** max(0, event.attempts - 1)),
                )
                event.next_retry_at = now + timedelta(seconds=delay)
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
        event_payload = event.safe_payload or {}
        for key in (
            "temporal_source",
            "provider_timestamp_confidence",
            "owner_binding_source",
        ):
            value = event_payload.get(key)
            if isinstance(value, str):
                metadata[key] = value
        for key in (
            "historical_owner_snapshot_mismatch",
            "current_owner_binding_verified",
            "historical_snapshot_preserved",
        ):
            value = event_payload.get(key)
            if isinstance(value, bool):
                metadata[key] = value
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
        elif payment.status == "failed" and payment.purpose in {
            "plan_change",
            "reactivation",
        }:
            pending = await repository.get_plan(payment.plan_code or "")
            if pending is not None and subscription.pending_plan_id == pending.id:
                subscription.pending_plan_id = None
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
        current_rank = _DECISION_RANK.get(payment.provider_decision, -1)
        incoming_rank = _DECISION_RANK[state]
        if (
            payment.checkout_intent_status == "cancelled"
            and payment.provider_payment_id is None
        ):
            current_rank = 1
        if incoming_rank < current_rank:
            return True
        return bool(
            incoming_rank == current_rank
            and occurred_at is not None
            and payment.provider_occurred_at is not None
            and _as_utc(occurred_at) < _as_utc(payment.provider_occurred_at)
        )

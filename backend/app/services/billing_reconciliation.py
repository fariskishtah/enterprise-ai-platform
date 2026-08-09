"""Append-only comparison of local billing projections to provider truth."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.providers import (
    PaymentProviderError,
    PaymentReconciliationProvider,
    ProviderReconciliationTarget,
    ProviderTransactionTruth,
)
from app.billing.queue import BillingWebhookQueue
from app.models.billing import (
    BillingAuditEvent,
    BillingReconciliationResult,
    BillingReconciliationRun,
    BillingWebhookEvent,
    Payment,
)
from app.models.user import User
from app.observability.metrics import record_billing_provider_reconciliation
from app.repositories.billing import BillingRepository

logger = logging.getLogger(__name__)

TemporalSource = Literal[
    "webhook_received_at",
    "reconciliation_observed_at",
    "provider_offset_timestamp",
]


class BillingReconciliationError(RuntimeError):
    """Safe failure for a reconciliation request."""


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    run_id: UUID
    dry_run: bool
    reused: bool
    outcomes: dict[str, int]
    compensating_event_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class AutomaticReconciliationSummary:
    scanned: int
    matched: int
    queued: int
    provider_missing: int
    manual_review: int
    provider_failures: int
    oldest_pending_age_seconds: float


@dataclass(frozen=True, slots=True)
class OwnerBindingEvidence:
    """Safe audit evidence for current account identity and historical drift."""

    historical_owner_snapshot_mismatch: bool
    current_owner_binding_verified: bool
    owner_binding_source: Literal["current_configuration"] = "current_configuration"
    historical_snapshot_preserved: bool = True

    def as_metadata(self) -> dict[str, object]:
        return {
            "historical_owner_snapshot_mismatch": (
                self.historical_owner_snapshot_mismatch
            ),
            "current_owner_binding_verified": self.current_owner_binding_verified,
            "owner_binding_source": self.owner_binding_source,
            "historical_snapshot_preserved": self.historical_snapshot_preserved,
        }


class BillingReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = BillingRepository(session)

    async def run(
        self,
        *,
        actor: User,
        provider: PaymentReconciliationProvider,
        environment: str,
        expected_callback_owner: str | None,
        idempotency_key: str,
        dry_run: bool,
        finance_approval_reference: str | None,
        limit: int = 100,
    ) -> ReconciliationSummary:
        existing = await self._repository.get_reconciliation_run(
            provider.name, environment, idempotency_key
        )
        if existing is not None:
            if existing.status != "completed":
                raise BillingReconciliationError(
                    "The prior reconciliation attempt did not complete; use a new "
                    "idempotency key only after provider retrieval is available."
                )
            stored_outcomes = existing.summary.get("outcomes", {})
            outcomes = {
                str(key): int(value)
                for key, value in (
                    stored_outcomes.items() if isinstance(stored_outcomes, dict) else ()
                )
            }
            return ReconciliationSummary(
                run_id=existing.id,
                dry_run=existing.dry_run,
                reused=True,
                outcomes=outcomes,
                compensating_event_ids=(),
            )
        if not dry_run and not (finance_approval_reference or "").strip():
            raise BillingReconciliationError(
                "A finance approval reference is required for compensating events."
            )

        run = BillingReconciliationRun(
            id=uuid4(),
            provider=provider.name,
            environment=environment,
            idempotency_key=idempotency_key,
            dry_run=dry_run,
            status="running",
            triggered_by_user_id=actor.id,
            finance_approval_reference=(finance_approval_reference or None),
            summary={},
        )
        self._repository.add_reconciliation_run(run)
        await self._session.commit()
        try:
            local = await self._repository.list_platform_provider_payments(
                provider.name, environment, limit=limit
            )
            comparisons: list[tuple[Payment, ProviderTransactionTruth | None]] = []
            for payment in local:
                truth = await provider.reconcile_transaction(
                    ProviderReconciliationTarget(
                        payment_reference=payment.id,
                        provider_payment_id=payment.provider_payment_id,
                        provider_order_id=payment.provider_order_id,
                    )
                )
                comparisons.append((payment, truth))
            truths = [truth for _payment, truth in comparisons if truth is not None]
            self._validate_truths(truths, environment=environment)
            summary = await self._compare(
                run=run,
                actor=actor,
                comparisons=comparisons,
                dry_run=dry_run,
                approval=finance_approval_reference,
                expected_callback_owner=expected_callback_owner,
            )
        except Exception:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.summary = {"outcomes": {}, "error": "provider_query_failed"}
            await self._session.commit()
            raise
        return summary

    @staticmethod
    def _validate_truths(
        truths: list[ProviderTransactionTruth], *, environment: str
    ) -> None:
        seen: set[str] = set()
        for truth in truths:
            if (
                not truth.provider_payment_id
                or truth.provider_payment_id in seen
                or truth.amount_minor <= 0
                or len(truth.currency) != 3
                or truth.environment not in {"sandbox", "live"}
                or truth.environment != environment
                or (
                    truth.provider_timestamp_confidence == "explicit"
                    and truth.occurred_at is None
                )
                or (
                    truth.provider_timestamp_confidence == "ambiguous"
                    and (truth.occurred_at is not None or not truth.provider_timestamp)
                )
            ):
                raise PaymentProviderError(
                    "The provider returned malformed reconciliation data.",
                    retryable=False,
                )
            seen.add(truth.provider_payment_id)

    async def _compare(
        self,
        *,
        run: BillingReconciliationRun,
        actor: User,
        comparisons: list[tuple[Payment, ProviderTransactionTruth | None]],
        dry_run: bool,
        approval: str | None,
        expected_callback_owner: str | None,
    ) -> ReconciliationSummary:
        outcomes: dict[str, int] = {}
        compensating: list[UUID] = []

        for payment, truth in comparisons:
            outcome = (
                "provider_missing"
                if truth is None
                else self._outcome(
                    payment,
                    truth,
                    expected_callback_owner=expected_callback_owner,
                )
            )
            if (
                outcome == "provider_missing"
                and payment.provider_decision == "succeeded_eligible"
            ):
                logger.critical(
                    "billing_reconciliation_local_success_provider_missing",
                    extra={
                        "run_id": str(run.id),
                        "payment_id": str(payment.id),
                        "provider": run.provider,
                    },
                )
            event_id: UUID | None = None
            if outcome == "state_mismatch" and not dry_run and truth is not None:
                event_id = await self._add_compensating_event(
                    run=run,
                    actor=actor,
                    payment=payment,
                    truth=truth,
                    approval=approval or "",
                    observed_at=datetime.now(UTC),
                    owner_binding=_owner_binding_evidence(
                        payment,
                        truth,
                        expected_callback_owner=expected_callback_owner,
                    ),
                )
                compensating.append(event_id)
                outcome = "corrected_by_compensating_event"
            self._add_result(
                run,
                payment,
                truth,
                outcome,
                event_id,
                expected_callback_owner=expected_callback_owner,
            )
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.summary = {
            "outcomes": outcomes,
            "compensating_event_count": len(compensating),
        }
        self._session.add(
            BillingAuditEvent(
                company_id=actor.company_id,
                actor_user_id=actor.id,
                action="billing.reconciliation_completed",
                result="succeeded",
                safe_metadata={
                    "run_id": str(run.id),
                    "provider": run.provider,
                    "environment": run.environment,
                    "dry_run": dry_run,
                    "outcomes": outcomes,
                },
            )
        )
        await self._session.commit()
        return ReconciliationSummary(
            run_id=run.id,
            dry_run=dry_run,
            reused=False,
            outcomes=outcomes,
            compensating_event_ids=tuple(compensating),
        )

    @staticmethod
    def _outcome(
        payment: Payment,
        truth: ProviderTransactionTruth,
        *,
        expected_callback_owner: str | None,
    ) -> str:
        if (
            truth.payment_reference != payment.id
            or (
                payment.provider_payment_id is not None
                and truth.provider_payment_id != payment.provider_payment_id
            )
            or (
                payment.provider_order_id is not None
                and truth.provider_order_id != payment.provider_order_id
            )
        ):
            return "manual_review_required"
        if not _owner_binding_evidence(
            payment,
            truth,
            expected_callback_owner=expected_callback_owner,
        ).current_owner_binding_verified:
            return "manual_review_required"
        if payment.amount_minor != truth.amount_minor:
            return "amount_mismatch"
        if payment.currency != truth.currency:
            return "currency_mismatch"
        if payment.provider_integration_id != truth.integration_id:
            return "integration_mismatch"
        if payment.environment != truth.environment:
            return "environment_mismatch"
        if payment.provider_decision != truth.decision:
            return "state_mismatch"
        return "matched"

    def _add_result(
        self,
        run: BillingReconciliationRun,
        payment: Payment | None,
        truth: ProviderTransactionTruth | None,
        outcome: str,
        event_id: UUID | None,
        *,
        expected_callback_owner: str | None,
    ) -> None:
        owner_binding = (
            _owner_binding_evidence(
                payment,
                truth,
                expected_callback_owner=expected_callback_owner,
            )
            if payment is not None and truth is not None
            else None
        )
        self._repository.add_reconciliation_result(
            BillingReconciliationResult(
                run_id=run.id,
                company_id=payment.company_id if payment is not None else None,
                payment_id=payment.id if payment is not None else None,
                provider_payment_id=(
                    truth.provider_payment_id
                    if truth is not None
                    else payment.provider_payment_id if payment is not None else None
                ),
                outcome=outcome,
                local_state=payment.provider_decision if payment is not None else None,
                provider_state=truth.decision if truth is not None else None,
                safe_details={
                    "amount_minor": truth.amount_minor if truth is not None else None,
                    "currency": truth.currency if truth is not None else None,
                    "integration_id": (
                        truth.integration_id if truth is not None else None
                    ),
                    "environment": truth.environment if truth is not None else None,
                    "provider_timestamp_confidence": (
                        truth.provider_timestamp_confidence
                        if truth is not None
                        else None
                    ),
                    **(
                        owner_binding.as_metadata() if owner_binding is not None else {}
                    ),
                },
                compensating_event_id=event_id,
            )
        )

    async def _add_compensating_event(
        self,
        *,
        run: BillingReconciliationRun,
        actor: User,
        payment: Payment,
        truth: ProviderTransactionTruth,
        approval: str,
        observed_at: datetime,
        owner_binding: OwnerBindingEvidence,
    ) -> UUID:
        trusted_webhook_received_at = (
            await self._repository.get_trusted_provider_event_received_at(
                run.provider,
                truth.provider_payment_id,
                payment.company_id,
            )
        )
        temporal_source, temporal_observed_at = _temporal_evidence(
            truth,
            observed_at=observed_at,
            webhook_received_at=trusted_webhook_received_at,
        )
        fingerprint = _reconciliation_fingerprint(truth)
        provider_event_id = f"reconciliation:{fingerprint}"
        existing = await self._repository.get_event_by_provider_id(
            run.provider, provider_event_id
        )
        if existing is not None:
            return existing.id
        event = BillingWebhookEvent(
            id=uuid4(),
            company_id=payment.company_id,
            provider=run.provider,
            provider_event_id=provider_event_id,
            raw_provider_event_id=truth.provider_payment_id,
            event_type="reconciliation.compensating",
            payload_hash=fingerprint.ljust(64, "0"),
            safe_payload=_compensating_payload(
                payment,
                truth,
                temporal_source=temporal_source,
                temporal_observed_at=temporal_observed_at,
                owner_binding=owner_binding,
            ),
            validation_outcome="accepted",
            status="queued",
            received_at=observed_at,
            queued_at=observed_at,
        )
        self._session.add(event)
        self._session.add(
            BillingAuditEvent(
                company_id=payment.company_id,
                actor_user_id=actor.id,
                action="billing.reconciliation_compensating_event",
                result="succeeded",
                safe_metadata={
                    "run_id": str(run.id),
                    "payment_id": str(payment.id),
                    "event_id": str(event.id),
                    "finance_approval_reference": approval,
                    "temporal_source": temporal_source,
                    "provider_timestamp_confidence": (
                        truth.provider_timestamp_confidence
                    ),
                    **owner_binding.as_metadata(),
                },
            )
        )
        return event.id


class AutomaticBillingReconciliationService:
    """Bounded recovery for aged payments using exact authenticated inquiry."""

    _CORRECTABLE_DECISIONS = {
        "succeeded_eligible",
        "failed",
        "cancelled",
        "refunded",
        "reversed",
    }

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: PaymentReconciliationProvider,
        queue: BillingWebhookQueue,
        *,
        environment: str,
        grace_seconds: int,
        expected_callback_owner: str | None,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._queue = queue
        self._environment = environment
        self._grace_seconds = grace_seconds
        self._expected_callback_owner = expected_callback_owner

    async def run(
        self, *, limit: int, now: datetime | None = None
    ) -> AutomaticReconciliationSummary:
        effective_now = now or datetime.now(UTC)
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            payments = await repository.list_aged_reconcilable_payments(
                self._provider.name,
                self._environment,
                created_before=effective_now - timedelta(seconds=self._grace_seconds),
                limit=limit,
            )

        matched = queued = provider_missing = manual_review = provider_failures = 0
        queued_ids: list[UUID] = []
        for payment in payments:
            target = ProviderReconciliationTarget(
                payment_reference=payment.id,
                provider_payment_id=payment.provider_payment_id,
                provider_order_id=payment.provider_order_id,
            )
            try:
                truth = await self._provider.reconcile_transaction(target)
                if truth is None:
                    provider_missing += 1
                    continue
                BillingReconciliationService._validate_truths(
                    [truth], environment=self._environment
                )
            except PaymentProviderError:
                provider_failures += 1
                logger.warning(
                    "billing_automatic_reconciliation_provider_failure",
                    extra={"provider": self._provider.name},
                )
                continue

            outcome = BillingReconciliationService._outcome(
                payment,
                truth,
                expected_callback_owner=self._expected_callback_owner,
            )
            if outcome == "matched":
                matched += 1
                continue
            if (
                outcome != "state_mismatch"
                or truth.decision not in self._CORRECTABLE_DECISIONS
            ):
                manual_review += 1
                continue

            event_id = await self._persist_compensating_event(
                payment,
                truth,
                observed_at=effective_now,
                owner_binding=_owner_binding_evidence(
                    payment,
                    truth,
                    expected_callback_owner=self._expected_callback_owner,
                ),
            )
            if event_id is not None:
                queued_ids.append(event_id)
                queued += 1

        for event_id in queued_ids:
            try:
                self._queue.enqueue(event_id)
            except Exception:
                provider_failures += 1
                logger.error(
                    "billing_automatic_reconciliation_queue_failure",
                    extra={"provider": self._provider.name},
                )

        oldest_pending_age = (
            max(
                (
                    effective_now
                    - (
                        payment.created_at
                        if payment.created_at.tzinfo is not None
                        else payment.created_at.replace(tzinfo=UTC)
                    )
                ).total_seconds()
                for payment in payments
            )
            if payments
            else 0.0
        )
        summary = AutomaticReconciliationSummary(
            scanned=len(payments),
            matched=matched,
            queued=queued,
            provider_missing=provider_missing,
            manual_review=manual_review,
            provider_failures=provider_failures,
            oldest_pending_age_seconds=max(oldest_pending_age, 0.0),
        )
        for outcome, count in (
            ("matched", summary.matched),
            ("provider_missing", summary.provider_missing),
            ("manual_review", summary.manual_review),
            ("provider_failure", summary.provider_failures),
            ("correction_queued", summary.queued),
        ):
            record_billing_provider_reconciliation(outcome=outcome, count=count)
        logger.info(
            "billing_automatic_reconciliation_completed",
            extra={
                "scanned": summary.scanned,
                "matched": summary.matched,
                "queued": summary.queued,
                "provider_missing": summary.provider_missing,
                "manual_review": summary.manual_review,
                "provider_failures": summary.provider_failures,
                "oldest_pending_age_seconds": summary.oldest_pending_age_seconds,
            },
        )
        return summary

    async def _persist_compensating_event(
        self,
        payment: Payment,
        truth: ProviderTransactionTruth,
        *,
        observed_at: datetime,
        owner_binding: OwnerBindingEvidence,
    ) -> UUID | None:
        fingerprint = _reconciliation_fingerprint(truth)
        provider_event_id = f"reconciliation:{fingerprint}"
        async with self._session_factory() as session:
            repository = BillingRepository(session)
            existing = await repository.get_event_by_provider_id(
                self._provider.name, provider_event_id
            )
            if existing is not None:
                return None
            trusted_webhook_received_at = (
                await repository.get_trusted_provider_event_received_at(
                    self._provider.name,
                    truth.provider_payment_id,
                    payment.company_id,
                )
            )
            temporal_source, temporal_observed_at = _temporal_evidence(
                truth,
                observed_at=observed_at,
                webhook_received_at=trusted_webhook_received_at,
            )
            safe_payload = _compensating_payload(
                payment,
                truth,
                temporal_source=temporal_source,
                temporal_observed_at=temporal_observed_at,
                owner_binding=owner_binding,
            )
            event = BillingWebhookEvent(
                id=uuid4(),
                company_id=payment.company_id,
                provider=self._provider.name,
                provider_event_id=provider_event_id,
                raw_provider_event_id=truth.provider_payment_id,
                event_type="reconciliation.compensating",
                payload_hash=hashlib.sha256(
                    json.dumps(
                        safe_payload, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                safe_payload=safe_payload,
                validation_outcome="accepted",
                status="queued",
                received_at=observed_at,
                queued_at=observed_at,
            )
            session.add(event)
            session.add(
                BillingAuditEvent(
                    company_id=payment.company_id,
                    actor_user_id=None,
                    action="billing.automatic_reconciliation_event",
                    result="succeeded",
                    safe_metadata={
                        "payment_id": str(payment.id),
                        "event_id": str(event.id),
                        "provider": self._provider.name,
                        "trigger": "aged_unresolved_payment",
                        "temporal_source": temporal_source,
                        "provider_timestamp_confidence": (
                            truth.provider_timestamp_confidence
                        ),
                        **owner_binding.as_metadata(),
                    },
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            return event.id


def _reconciliation_fingerprint(truth: ProviderTransactionTruth) -> str:
    return hashlib.sha256(
        f"{truth.provider_payment_id}:{truth.decision}".encode()
    ).hexdigest()[:32]


def _owner_binding_evidence(
    payment: Payment,
    truth: ProviderTransactionTruth,
    *,
    expected_callback_owner: str | None,
) -> OwnerBindingEvidence:
    current_owner = (expected_callback_owner or "").strip()
    return OwnerBindingEvidence(
        historical_owner_snapshot_mismatch=bool(
            payment.provider_merchant_id is not None
            and current_owner
            and payment.provider_merchant_id != current_owner
        ),
        current_owner_binding_verified=bool(
            current_owner and truth.merchant_id == current_owner
        ),
    )


def _temporal_evidence(
    truth: ProviderTransactionTruth,
    *,
    observed_at: datetime,
    webhook_received_at: datetime | None,
) -> tuple[TemporalSource, datetime]:
    if truth.provider_timestamp_confidence == "explicit":
        if truth.occurred_at is None:
            raise PaymentProviderError(
                "The provider returned malformed reconciliation data.",
                retryable=False,
            )
        return "provider_offset_timestamp", truth.occurred_at
    if webhook_received_at is not None:
        return "webhook_received_at", webhook_received_at
    return "reconciliation_observed_at", observed_at


def _compensating_payload(
    payment: Payment,
    truth: ProviderTransactionTruth,
    *,
    temporal_source: TemporalSource,
    temporal_observed_at: datetime,
    owner_binding: OwnerBindingEvidence,
) -> dict[str, object]:
    return {
        "payment_reference": str(payment.id),
        "provider_payment_id": truth.provider_payment_id,
        "amount_minor": truth.amount_minor,
        "currency": truth.currency,
        "state": (
            "succeeded" if truth.decision == "succeeded_eligible" else truth.decision
        ),
        "decision": truth.decision,
        "occurred_at": (
            truth.occurred_at.isoformat() if truth.occurred_at is not None else None
        ),
        "integration_id": truth.integration_id,
        "environment": truth.environment,
        "merchant_id": truth.merchant_id,
        "provider_order_id": truth.provider_order_id,
        "source_type": truth.source_type,
        "provider_timestamp": truth.provider_timestamp,
        "provider_timestamp_confidence": truth.provider_timestamp_confidence,
        "temporal_source": temporal_source,
        "temporal_observed_at": temporal_observed_at.isoformat(),
        **owner_binding.as_metadata(),
        "validation_outcome": "accepted",
    }

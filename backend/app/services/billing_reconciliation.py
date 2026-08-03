"""Append-only comparison of local billing projections to provider truth."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers import (
    PaymentProviderError,
    PaymentReconciliationProvider,
    ProviderTransactionTruth,
)
from app.models.billing import (
    BillingAuditEvent,
    BillingReconciliationResult,
    BillingReconciliationRun,
    BillingWebhookEvent,
    Payment,
)
from app.models.user import User
from app.repositories.billing import BillingRepository

logger = logging.getLogger(__name__)


class BillingReconciliationError(RuntimeError):
    """Safe failure for a reconciliation request."""


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    run_id: UUID
    dry_run: bool
    reused: bool
    outcomes: dict[str, int]
    compensating_event_ids: tuple[UUID, ...]


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
        idempotency_key: str,
        dry_run: bool,
        finance_approval_reference: str | None,
    ) -> ReconciliationSummary:
        existing = await self._repository.get_reconciliation_run(
            provider.name, environment, idempotency_key
        )
        if existing is not None:
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
            truths = await provider.list_reconciliation_transactions()
            self._validate_truths(truths, environment=environment)
            summary = await self._compare(
                run=run,
                actor=actor,
                truths=truths,
                dry_run=dry_run,
                approval=finance_approval_reference,
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
        truths: list[ProviderTransactionTruth],
        dry_run: bool,
        approval: str | None,
    ) -> ReconciliationSummary:
        local = await self._repository.list_platform_provider_payments(run.provider)
        local_by_provider_id = {
            payment.provider_payment_id: payment
            for payment in local
            if payment.provider_payment_id is not None
        }
        truths_by_id = {item.provider_payment_id: item for item in truths}
        outcomes: dict[str, int] = {}
        compensating: list[UUID] = []

        for payment in local:
            assert payment.provider_payment_id is not None
            truth = truths_by_id.get(payment.provider_payment_id)
            outcome = (
                "provider_missing" if truth is None else self._outcome(payment, truth)
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
                )
                compensating.append(event_id)
                outcome = "corrected_by_compensating_event"
            self._add_result(run, payment, truth, outcome, event_id)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

        for truth in truths:
            if truth.provider_payment_id in local_by_provider_id:
                continue
            self._add_result(run, None, truth, "local_missing", None)
            outcomes["local_missing"] = outcomes.get("local_missing", 0) + 1
            if truth.decision == "succeeded_eligible":
                logger.critical(
                    "billing_reconciliation_unknown_provider_success",
                    extra={
                        "run_id": str(run.id),
                        "provider_payment_id": truth.provider_payment_id,
                        "provider": run.provider,
                    },
                )

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
    def _outcome(payment: Payment, truth: ProviderTransactionTruth) -> str:
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
    ) -> None:
        self._repository.add_reconciliation_result(
            BillingReconciliationResult(
                run_id=run.id,
                company_id=payment.company_id if payment is not None else None,
                payment_id=payment.id if payment is not None else None,
                provider_payment_id=(
                    truth.provider_payment_id
                    if truth is not None
                    else payment.provider_payment_id
                    if payment is not None
                    else None
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
    ) -> UUID:
        fingerprint = hashlib.sha256(
            f"{truth.provider_payment_id}:{truth.decision}:{truth.occurred_at.isoformat()}".encode()
        ).hexdigest()[:32]
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
            safe_payload={
                "payment_reference": str(payment.id),
                "provider_payment_id": truth.provider_payment_id,
                "amount_minor": truth.amount_minor,
                "currency": truth.currency,
                "state": (
                    "succeeded"
                    if truth.decision == "succeeded_eligible"
                    else truth.decision
                ),
                "decision": truth.decision,
                "occurred_at": truth.occurred_at.isoformat(),
                "integration_id": truth.integration_id,
                "environment": truth.environment,
                "merchant_id": truth.merchant_id,
                "provider_order_id": truth.provider_order_id,
                "validation_outcome": "accepted",
            },
            validation_outcome="accepted",
            status="queued",
            queued_at=datetime.now(UTC),
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
                },
            )
        )
        return event.id

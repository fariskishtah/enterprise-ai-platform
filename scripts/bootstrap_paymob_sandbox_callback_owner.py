"""Validate persisted Sandbox callbacks and stage their common owner privately.

This script is sent over stdin to the already-running Sandbox backend container.
It never prints the callback owner and never mutates application data.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from app.config.settings import get_settings
from app.db.session import build_session_factory
from app.models.billing import BillingWebhookEvent, Payment

_OUTPUT_PATH = Path("/tmp/factorymind-paymob-expected-callback-owner")
_EXPECTED_DATABASE = "factorymind_paymob_sandbox"


class CallbackOwnerEvidenceError(RuntimeError):
    """The persisted records do not prove one expected Sandbox callback owner."""


@dataclass(frozen=True, slots=True)
class CallbackOwnerEvidence:
    """Card-free callback evidence paired with its checkout-time payment snapshot."""

    evidence_key: str
    event_status: str
    event_type: str
    validation_outcome: str
    safe_validation_outcome: str
    last_error_category: str | None
    attempts: int
    queued: bool
    terminal: bool
    owner: str
    integration_id: int | None
    environment: str | None
    decision: str
    state: str
    source_type: str | None
    amount_minor: int
    currency: str
    payment_present: bool
    payment_company_matches: bool
    payment_provider: str | None
    payment_integration_id: int | None
    payment_environment: str | None
    payment_amount_minor: int | None
    payment_currency: str | None


def validate_sandbox_runtime(
    *,
    environment: str,
    app_environment: str,
    payment_provider: str,
    sandbox_mode: bool,
    database_name: str,
) -> None:
    """Refuse any non-Sandbox runtime before inspecting evidence."""

    if environment.lower() == "production" or app_environment.lower() == "production":
        raise CallbackOwnerEvidenceError("Production runtime is forbidden.")
    if environment.lower() != "staging" or app_environment.lower() != "staging":
        raise CallbackOwnerEvidenceError("The runtime is not the staging Sandbox.")
    if payment_provider != "paymob" or not sandbox_mode:
        raise CallbackOwnerEvidenceError("Paymob Test Mode is not enabled.")
    if database_name != _EXPECTED_DATABASE:
        raise CallbackOwnerEvidenceError("The database is not the Paymob Sandbox.")


def validated_callback_owner(
    evidence: list[CallbackOwnerEvidence], *, expected_integration_id: int
) -> str:
    """Return one proven owner without weakening any callback binding."""

    if len(evidence) < 2:
        raise CallbackOwnerEvidenceError(
            "At least two authenticated callback records are required."
        )
    if len({item.evidence_key for item in evidence}) != len(evidence):
        raise CallbackOwnerEvidenceError("Callback evidence is not distinct.")

    owners: set[str] = set()
    quote_evidence: set[tuple[int, str]] = set()
    for item in evidence:
        authenticated_business_quarantine = (
            item.event_status == "quarantined"
            and item.event_type == "transaction.captured"
            and item.validation_outcome == "quarantined_wrong_merchant"
            and item.safe_validation_outcome == "quarantined_wrong_merchant"
            and item.last_error_category == "quarantined_wrong_merchant"
            and item.attempts == 0
            and not item.queued
            and item.terminal
        )
        if not authenticated_business_quarantine:
            raise CallbackOwnerEvidenceError(
                "Evidence is not an authenticated wrong-owner quarantine."
            )
        if not item.owner.isdigit() or int(item.owner) <= 0:
            raise CallbackOwnerEvidenceError("Callback owner evidence is invalid.")
        if (
            item.integration_id != expected_integration_id
            or item.environment != "sandbox"
            or item.decision != "succeeded_eligible"
            or item.state != "succeeded"
            or item.source_type != "card"
        ):
            raise CallbackOwnerEvidenceError(
                "Callback integration or Sandbox semantics are inconsistent."
            )
        if (
            not item.payment_present
            or not item.payment_company_matches
            or item.payment_provider != "paymob"
            or item.payment_integration_id != expected_integration_id
            or item.payment_environment != "sandbox"
            or item.payment_amount_minor != item.amount_minor
            or item.payment_currency != item.currency
        ):
            raise CallbackOwnerEvidenceError(
                "Callback amount, currency, or payment binding is inconsistent."
            )
        owners.add(item.owner)
        quote_evidence.add((item.amount_minor, item.currency))

    if len(owners) != 1:
        raise CallbackOwnerEvidenceError("Callback owners disagree.")
    if len(quote_evidence) != 1:
        raise CallbackOwnerEvidenceError("Callback quote evidence disagrees.")
    return next(iter(owners))


async def _collect_evidence() -> tuple[list[CallbackOwnerEvidence], int]:
    settings = get_settings()
    if settings.paymob_integration_id is None:
        raise CallbackOwnerEvidenceError("The Sandbox integration is missing.")
    session_factory = build_session_factory(settings.database_url)
    try:
        async with session_factory() as session:
            database_name = str(await session.scalar(text("SELECT current_database()")))
            validate_sandbox_runtime(
                environment=os.environ.get("ENVIRONMENT", ""),
                app_environment=os.environ.get("APP_ENV", ""),
                payment_provider=settings.payment_provider,
                sandbox_mode=settings.payment_sandbox_mode,
                database_name=database_name,
            )
            events = (
                await session.scalars(
                    select(BillingWebhookEvent)
                    .where(
                        BillingWebhookEvent.provider == "paymob",
                        BillingWebhookEvent.validation_outcome
                        == "quarantined_wrong_merchant",
                    )
                    .order_by(BillingWebhookEvent.received_at)
                )
            ).all()
            collected: list[CallbackOwnerEvidence] = []
            for event in events:
                payload = event.safe_payload or {}
                reference = payload.get("payment_reference")
                payment = None
                try:
                    payment = await session.get(Payment, UUID(str(reference)))
                except (TypeError, ValueError):
                    pass
                amount_value = payload.get("amount_minor")
                integration_value = payload.get("integration_id")
                try:
                    amount_minor = int(amount_value)
                    integration_id = int(integration_value)
                except (TypeError, ValueError) as exc:
                    raise CallbackOwnerEvidenceError(
                        "Normalized callback evidence is malformed."
                    ) from exc
                collected.append(
                    CallbackOwnerEvidence(
                        evidence_key=event.provider_event_id,
                        event_status=event.status,
                        event_type=event.event_type,
                        validation_outcome=event.validation_outcome,
                        safe_validation_outcome=str(
                            payload.get("validation_outcome", "")
                        ),
                        last_error_category=event.last_error_category,
                        attempts=event.attempts,
                        queued=event.queued_at is not None,
                        terminal=event.processed_at is not None,
                        owner=str(payload.get("merchant_id", "")),
                        integration_id=integration_id,
                        environment=(
                            str(payload["environment"])
                            if payload.get("environment") is not None
                            else None
                        ),
                        decision=str(payload.get("decision", "")),
                        state=str(payload.get("state", "")),
                        source_type=(
                            str(payload["source_type"]).lower()
                            if payload.get("source_type") is not None
                            else None
                        ),
                        amount_minor=amount_minor,
                        currency=str(payload.get("currency", "")),
                        payment_present=payment is not None,
                        payment_company_matches=bool(
                            payment
                            and event.company_id is not None
                            and payment.company_id == event.company_id
                        ),
                        payment_provider=payment.provider if payment else None,
                        payment_integration_id=(
                            payment.provider_integration_id if payment else None
                        ),
                        payment_environment=payment.environment if payment else None,
                        payment_amount_minor=payment.amount_minor if payment else None,
                        payment_currency=payment.currency if payment else None,
                    )
                )
            return collected, settings.paymob_integration_id
    finally:
        await session_factory.kw["bind"].dispose()


def _write_private_owner(owner: str) -> None:
    descriptor = os.open(
        _OUTPUT_PATH,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        os.write(descriptor, owner.encode("ascii"))
    finally:
        os.close(descriptor)


async def _run() -> None:
    evidence, expected_integration_id = await _collect_evidence()
    owner = validated_callback_owner(
        evidence, expected_integration_id=expected_integration_id
    )
    _write_private_owner(owner)


def main() -> int:
    try:
        asyncio.run(_run())
    except (CallbackOwnerEvidenceError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Sandbox callback-owner evidence validated; identifier was not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

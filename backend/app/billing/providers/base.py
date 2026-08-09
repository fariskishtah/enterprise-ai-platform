"""Provider-neutral hosted-checkout and webhook contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

PaymentState = Literal[
    "pending", "succeeded", "failed", "cancelled", "refunded", "reversed"
]
PaymentDecision = Literal[
    "pending",
    "authorized_not_captured",
    "succeeded_eligible",
    "failed",
    "cancelled",
    "expired",
    "refunded",
    "reversed",
    "under_review",
    "quarantined",
]
ProviderValidationOutcome = Literal[
    "accepted",
    "duplicate",
    "quarantined_invalid_hmac",
    "quarantined_wrong_integration",
    "quarantined_wrong_environment",
    "quarantined_wrong_merchant",
    "quarantined_wrong_amount",
    "quarantined_wrong_currency",
    "quarantined_unknown_payment",
    "quarantined_unsupported_semantics",
]


class PaymentProviderError(RuntimeError):
    """A safe provider failure that callers may classify for retry."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class PaymentProviderConfigurationError(PaymentProviderError):
    """The selected provider is unavailable or incompletely configured."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class PaymentProviderSignatureError(PaymentProviderError):
    """A callback failed provider authentication."""

    def __init__(self) -> None:
        super().__init__("The payment callback signature is invalid.", retryable=False)


@dataclass(frozen=True, slots=True)
class CheckoutRequest:
    """Backend-authoritative checkout inputs sent to a hosted provider UI."""

    reference: UUID
    plan_code: str
    plan_name: str
    amount_minor: int
    currency: str
    email: str
    first_name: str
    last_name: str
    phone_number: str
    city: str
    country: str
    street: str
    return_reference: str = ""


@dataclass(frozen=True, slots=True)
class HostedCheckout:
    """Non-sensitive hosted-checkout coordinates safe to expose to a browser."""

    provider_checkout_id: str
    checkout_url: str
    provider_customer_id: str | None = None
    provider_order_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderWebhook:
    """Authenticated, normalized transaction state from a provider callback."""

    provider_event_id: str
    raw_provider_event_id: str
    event_type: str
    payment_reference: UUID
    provider_payment_id: str
    amount_minor: int
    currency: str
    state: PaymentState
    occurred_at: datetime | None
    failure_code: str | None = None
    provider_customer_id: str | None = None
    decision: PaymentDecision | None = None
    validation_outcome: ProviderValidationOutcome = "accepted"
    integration_id: int | None = None
    environment: Literal["sandbox", "live"] | None = None
    merchant_id: str | None = None
    provider_order_id: str | None = None
    source_type: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderTransactionTruth:
    """Card-free provider truth consumed by reconciliation."""

    provider_payment_id: str
    payment_reference: UUID | None
    amount_minor: int
    currency: str
    decision: PaymentDecision
    integration_id: int
    environment: Literal["sandbox", "live"]
    occurred_at: datetime
    merchant_id: str | None = None
    provider_order_id: str | None = None
    source_type: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderReconciliationTarget:
    """Exact persisted coordinates allowed for a read-only provider inquiry."""

    payment_reference: UUID
    provider_payment_id: str | None = None
    provider_order_id: str | None = None


class PaymentReconciliationProvider(Protocol):
    name: str

    async def reconcile_transaction(
        self, target: ProviderReconciliationTarget
    ) -> ProviderTransactionTruth | None:
        """Return authenticated provider truth for one exact local payment."""


class PaymentProvider(Protocol):
    """Narrow boundary that keeps provider details out of billing use cases."""

    name: str

    async def create_checkout(self, request: CheckoutRequest) -> HostedCheckout:
        """Create a provider-hosted checkout without accepting raw card data."""

    def parse_webhook(
        self, payload: dict[str, object], *, signature: str
    ) -> ProviderWebhook:
        """Authenticate and normalize one callback."""

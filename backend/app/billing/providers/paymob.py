"""Paymob Intention API and transaction-callback adapter.

The adapter follows Paymob's hosted Unified Checkout flow. It never accepts or
transmits card details; those are collected only on Paymob's hosted page.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx

from app.billing.providers.base import (
    CheckoutRequest,
    HostedCheckout,
    PaymentDecision,
    PaymentProviderConfigurationError,
    PaymentProviderError,
    PaymentProviderSignatureError,
    PaymentState,
    ProviderTransactionTruth,
    ProviderValidationOutcome,
    ProviderWebhook,
)

_HMAC_FIELDS = (
    "amount",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order",
    "owner",
    "pending",
    "source_data_pan",
    "source_data_sub_type",
    "source_data_type",
    "success",
)


@dataclass(frozen=True, slots=True)
class PaymobConfiguration:
    secret_key: str
    public_key: str
    hmac_secret: str
    integration_id: int
    base_url: str
    webhook_url: str
    success_url: str
    failure_url: str
    currency: str
    sandbox_mode: bool
    timeout_seconds: float
    expected_callback_owner: int | None = None
    allowed_checkout_hosts: tuple[str, ...] = ("accept.paymob.com",)
    supported_source_types: tuple[str, ...] = ("card",)


def _canonical_scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        identifier = value.get("id")
        return "" if identifier is None else str(identifier)
    return str(value)


def _hmac_value(obj: dict[str, Any], field: str) -> object:
    if field == "amount":
        return obj.get("amount", obj.get("amount_cents"))
    if field == "source_data_pan":
        source_data = obj.get("source_data")
        return source_data.get("pan") if isinstance(source_data, dict) else None
    if field == "source_data_sub_type":
        source_data = obj.get("source_data")
        return source_data.get("sub_type") if isinstance(source_data, dict) else None
    if field == "source_data_type":
        source_data = obj.get("source_data")
        return source_data.get("type") if isinstance(source_data, dict) else None
    return obj.get(field)


def calculate_transaction_hmac(obj: dict[str, Any], secret: str) -> str:
    """Calculate Paymob's documented transaction-callback SHA-512 HMAC."""
    message = "".join(
        _canonical_scalar(_hmac_value(obj, field)) for field in _HMAC_FIELDS
    )
    return hmac.new(secret.encode(), message.encode(), hashlib.sha512).hexdigest()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _safe_failure_code(obj: dict[str, Any]) -> str | None:
    data = obj.get("data")
    if not isinstance(data, dict):
        return None
    candidate = data.get("message") or data.get("response_code")
    if candidate is None:
        return None
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(candidate)).strip("_")
    return normalized[:80] or None


class PaymobPaymentProvider:
    """Hosted checkout using Paymob's current Intention API."""

    name = "paymob"

    def __init__(
        self,
        configuration: PaymobConfiguration,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._configuration = configuration
        self._client = client

    async def create_checkout(self, request: CheckoutRequest) -> HostedCheckout:
        if request.currency != self._configuration.currency:
            raise PaymentProviderError(
                "The checkout currency does not match provider configuration.",
                retryable=False,
            )
        payload = {
            "amount": request.amount_minor,
            "currency": request.currency,
            "payment_methods": [self._configuration.integration_id],
            "items": [
                {
                    "name": request.plan_name,
                    "amount": request.amount_minor,
                    "description": f"{request.plan_code} monthly subscription",
                    "quantity": 1,
                }
            ],
            "billing_data": {
                "apartment": "NA",
                "first_name": request.first_name,
                "last_name": request.last_name,
                "street": request.street,
                "building": "NA",
                "phone_number": request.phone_number,
                "city": request.city,
                "country": request.country,
                "email": request.email,
                "floor": "NA",
                "state": "NA",
                "postal_code": "NA",
            },
            "special_reference": str(request.reference),
            "notification_url": self._configuration.webhook_url,
            "redirection_url": self._return_url(
                self._configuration.success_url, request.return_reference
            ),
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(
                    timeout=self._configuration.timeout_seconds
                ) as client:
                    response = await self._post_intention(client, payload)
            else:
                response = await self._post_intention(self._client, payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise PaymentProviderError(
                "Paymob did not respond while creating checkout.", retryable=True
            ) from exc

        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise PaymentProviderError(
                "Paymob temporarily rejected checkout creation.", retryable=True
            )
        if not response.is_success:
            raise PaymentProviderError(
                "Paymob rejected checkout creation.", retryable=False
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise PaymentProviderError(
                "Paymob returned an invalid checkout response.", retryable=True
            ) from exc
        checkout_id = body.get("id")
        client_secret = body.get("client_secret")
        if (
            checkout_id is None
            or not isinstance(client_secret, str)
            or not client_secret
        ):
            raise PaymentProviderError(
                "Paymob returned an incomplete checkout response.", retryable=True
            )
        query = urlencode(
            {
                "publicKey": self._configuration.public_key,
                "clientSecret": client_secret,
            }
        )
        checkout_url = (
            f"{self._configuration.base_url.rstrip('/')}/unifiedcheckout/?{query}"
        )
        parsed_checkout = urlsplit(checkout_url)
        if (
            parsed_checkout.scheme != "https"
            or (parsed_checkout.hostname or "").lower()
            not in self._configuration.allowed_checkout_hosts
        ):
            raise PaymentProviderError(
                "Paymob returned a checkout URL outside the configured allowlist.",
                retryable=False,
            )
        return HostedCheckout(
            provider_checkout_id=str(checkout_id),
            checkout_url=checkout_url,
        )

    @staticmethod
    def _return_url(base_url: str, reference: str) -> str:
        if not reference:
            return base_url
        parsed = urlsplit(base_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["state"] = reference
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")
        )

    async def _post_intention(
        self, client: httpx.AsyncClient, payload: dict[str, object]
    ) -> httpx.Response:
        return await client.post(
            f"{self._configuration.base_url.rstrip('/')}/v1/intention/",
            headers={"Authorization": f"Token {self._configuration.secret_key}"},
            json=payload,
        )

    def parse_webhook(
        self, payload: dict[str, object], *, signature: str
    ) -> ProviderWebhook:
        callback_type = payload.get("type")
        if callback_type is not None and callback_type != "TRANSACTION":
            raise PaymentProviderError(
                "Paymob callback type is not supported.", retryable=False
            )
        obj_value = payload.get("obj", payload)
        if not isinstance(obj_value, dict):
            raise PaymentProviderError(
                "Paymob returned an invalid callback object.", retryable=False
            )
        obj: dict[str, Any] = obj_value
        expected = calculate_transaction_hmac(obj, self._configuration.hmac_secret)
        if not re.fullmatch(r"[0-9a-fA-F]{128}", signature) or not hmac.compare_digest(
            expected, signature.lower()
        ):
            raise PaymentProviderSignatureError()

        raw_event_id = obj.get("id")
        order = obj.get("order")
        reference_value = (
            order.get("merchant_order_id") if isinstance(order, dict) else None
        ) or obj.get("special_reference")
        amount_value = obj.get("amount", obj.get("amount_cents"))
        currency = obj.get("currency")
        if (
            raw_event_id is None
            or amount_value is None
            or not isinstance(currency, str)
        ):
            raise PaymentProviderError(
                "Paymob callback is missing transaction fields.", retryable=False
            )
        try:
            payment_reference = UUID(str(reference_value))
            amount_minor = int(amount_value)
        except (TypeError, ValueError) as exc:
            raise PaymentProviderError(
                "Paymob callback has an invalid payment reference or amount.",
                retryable=False,
            ) from exc
        decision, state, event_type = self._decision(obj)
        validation_outcome = self._validation_outcome(obj, decision=decision)
        raw_id = str(raw_event_id)
        fingerprint = hashlib.sha256(
            json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        return ProviderWebhook(
            provider_event_id=f"transaction:{raw_id}:{event_type}:{fingerprint}",
            raw_provider_event_id=raw_id,
            event_type=event_type,
            payment_reference=payment_reference,
            provider_payment_id=raw_id,
            amount_minor=amount_minor,
            currency=currency.upper(),
            state=state,
            occurred_at=_parse_timestamp(
                obj.get("updated_at") or obj.get("created_at")
            ),
            failure_code=_safe_failure_code(obj) if state == "failed" else None,
            decision=decision,
            validation_outcome=validation_outcome,
            integration_id=self._integer(obj.get("integration_id")),
            environment=(
                "live"
                if obj.get("is_live") is True
                else "sandbox"
                if obj.get("is_live") is False
                else None
            ),
            merchant_id=(str(obj["owner"]) if obj.get("owner") is not None else None),
            provider_order_id=(
                str(order.get("id"))
                if isinstance(order, dict) and order.get("id") is not None
                else None
            ),
            source_type=self._source_type(obj),
        )

    def _validation_outcome(
        self, obj: dict[str, Any], *, decision: str
    ) -> ProviderValidationOutcome:
        if (
            self._integer(obj.get("integration_id"))
            != self._configuration.integration_id
        ):
            return "quarantined_wrong_integration"
        is_live = obj.get("is_live")
        if not isinstance(is_live, bool) or is_live == self._configuration.sandbox_mode:
            return "quarantined_wrong_environment"
        if (
            self._configuration.expected_callback_owner is not None
            and self._integer(obj.get("owner"))
            != self._configuration.expected_callback_owner
        ):
            return "quarantined_wrong_merchant"
        source_type = self._source_type(obj)
        if (
            source_type is None
            or source_type.lower() not in self._configuration.supported_source_types
            or decision == "under_review"
        ):
            return "quarantined_unsupported_semantics"
        return "accepted"

    @staticmethod
    def _source_type(obj: dict[str, Any]) -> str | None:
        source = obj.get("source_data")
        value = source.get("type") if isinstance(source, dict) else None
        return str(value).lower() if value is not None else None

    @staticmethod
    def _integer(value: object) -> int | None:
        try:
            return (
                int(value)
                if isinstance(value, (str, int)) and not isinstance(value, bool)
                else None
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _decision(
        obj: dict[str, Any],
    ) -> tuple[PaymentDecision, PaymentState, str]:
        if obj.get("is_refunded") is True or obj.get("is_refund") is True:
            return "refunded", "refunded", "transaction.refunded"
        if obj.get("is_voided") is True or obj.get("is_void") is True:
            return "reversed", "reversed", "transaction.reversed"
        if obj.get("success") is True and obj.get("pending") is not True:
            if (
                obj.get("is_auth") is True
                and obj.get("is_capture") is not True
                and obj.get("is_standalone_payment") is not True
            ):
                return (
                    "authorized_not_captured",
                    "pending",
                    "transaction.authorized",
                )
            if (
                obj.get("is_capture") is True
                or obj.get("is_standalone_payment") is True
            ):
                return "succeeded_eligible", "succeeded", "transaction.captured"
            return "under_review", "pending", "transaction.under_review"
        if obj.get("pending") is True:
            return "pending", "pending", "transaction.pending"
        return "failed", "failed", "transaction.failed"

    async def list_reconciliation_transactions(
        self,
    ) -> list[ProviderTransactionTruth]:
        """Fail closed until Paymob's query contract passes sandbox acceptance."""
        raise PaymentProviderConfigurationError(
            "Paymob provider reconciliation requires an accepted sandbox query "
            "contract."
        )

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
from datetime import UTC, datetime
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
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
    ProviderReconciliationTarget,
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
_RECONCILIATION_MAX_PAGES = 5


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
    api_key: str | None = None
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
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return None if parsed.tzinfo is None else parsed.astimezone(UTC)


def _provider_timestamp_evidence(
    obj: dict[str, Any],
) -> tuple[datetime | None, str | None, Literal["explicit", "ambiguous"]]:
    """Prefer an offset-qualified provider timestamp without inventing a zone."""
    raw_values = tuple(
        value.strip()
        for field in ("paid_at", "updated_at", "created_at")
        if isinstance((value := obj.get(field)), str) and value.strip()
    )
    for raw_value in raw_values:
        parsed = _parse_timestamp(raw_value)
        if parsed is not None:
            return parsed, raw_value, "explicit"
    return None, (raw_values[0] if raw_values else None), "ambiguous"


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
                    "description": f"{request.plan_code} prepaid access period",
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
        provider_order_id = body.get("intention_order_id")
        client_secret = body.get("client_secret")
        if (
            checkout_id is None
            or provider_order_id is None
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
            provider_order_id=str(provider_order_id),
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
                else "sandbox" if obj.get("is_live") is False else None
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

    async def reconcile_transaction(
        self, target: ProviderReconciliationTarget
    ) -> ProviderTransactionTruth | None:
        """Query one exact transaction/order through Paymob's inquiry API."""
        if not self._configuration.api_key:
            raise PaymentProviderConfigurationError(
                "Paymob reconciliation requires the account API key."
            )
        try:
            if self._client is None:
                async with httpx.AsyncClient(
                    timeout=self._configuration.timeout_seconds
                ) as client:
                    return await self._reconcile_with_client(client, target)
            return await self._reconcile_with_client(self._client, target)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise PaymentProviderError(
                "Paymob reconciliation did not respond.", retryable=True
            ) from exc

    async def _reconcile_with_client(
        self,
        client: httpx.AsyncClient,
        target: ProviderReconciliationTarget,
    ) -> ProviderTransactionTruth | None:
        token_response = await client.post(
            f"{self._configuration.base_url.rstrip('/')}/api/auth/tokens",
            json={"api_key": self._configuration.api_key},
        )
        if token_response.status_code >= 500 or token_response.status_code in {
            408,
            429,
        }:
            raise PaymentProviderError(
                "Paymob reconciliation authentication is temporarily unavailable.",
                retryable=True,
            )
        if not token_response.is_success:
            raise PaymentProviderConfigurationError(
                "Paymob reconciliation authentication was rejected."
            )
        try:
            token_body = token_response.json()
        except ValueError as exc:
            raise PaymentProviderError(
                "Paymob returned invalid reconciliation authentication data.",
                retryable=True,
            ) from exc
        token = token_body.get("token") if isinstance(token_body, dict) else None
        if not isinstance(token, str) or not token:
            raise PaymentProviderError(
                "Paymob returned incomplete reconciliation authentication data.",
                retryable=True,
            )

        if target.provider_payment_id:
            response = await client.get(
                f"{self._configuration.base_url.rstrip('/')}/api/acceptance/transactions/"
                f"{quote(target.provider_payment_id, safe='')}",
                params={"token": token},
            )
            if response.status_code == 404:
                return None
            body = self._inquiry_body(response)
            return self._transaction_truth(body, target=target)

        if target.provider_order_id:
            response = await client.get(
                f"{self._configuration.base_url.rstrip('/')}/api/ecommerce/orders/"
                f"{quote(target.provider_order_id, safe='')}",
                params={"token": token},
            )
            if response.status_code == 404:
                return None
            order = self._inquiry_body(response)
            transactions = order.get("transactions")
            if not isinstance(transactions, list):
                raise PaymentProviderError(
                    "Paymob returned malformed reconciliation order data.",
                    retryable=False,
                )
            matches: list[ProviderTransactionTruth] = []
            for candidate in transactions:
                if not isinstance(candidate, dict):
                    raise PaymentProviderError(
                        "Paymob returned malformed reconciliation transaction data.",
                        retryable=False,
                    )
                normalized_candidate = dict(candidate)
                candidate_order = normalized_candidate.get("order")
                if not isinstance(candidate_order, dict):
                    normalized_candidate["order"] = {
                        "id": order.get("id", target.provider_order_id),
                        "merchant_order_id": order.get("merchant_order_id"),
                    }
                truth = self._transaction_truth(normalized_candidate, target=target)
                if truth.payment_reference == target.payment_reference:
                    matches.append(truth)
            return self._one_reconciliation_match(matches)

        return await self._find_transaction_by_reference(client, token, target)

    async def _find_transaction_by_reference(
        self,
        client: httpx.AsyncClient,
        token: str,
        target: ProviderReconciliationTarget,
    ) -> ProviderTransactionTruth | None:
        matches: list[ProviderTransactionTruth] = []
        for page in range(1, _RECONCILIATION_MAX_PAGES + 1):
            response = await client.get(
                f"{self._configuration.base_url.rstrip('/')}/api/acceptance/transactions",
                params={"page": page, "token": token},
            )
            body = self._inquiry_collection(response)
            if not body:
                break
            for candidate in body:
                if not isinstance(candidate, dict):
                    raise PaymentProviderError(
                        "Paymob returned malformed reconciliation transaction data.",
                        retryable=False,
                    )
                reference = self._transaction_reference(candidate)
                if reference != target.payment_reference:
                    continue
                matches.append(self._transaction_truth(candidate, target=target))
            if len(matches) > 1:
                break
        return self._one_reconciliation_match(matches)

    @staticmethod
    def _one_reconciliation_match(
        matches: list[ProviderTransactionTruth],
    ) -> ProviderTransactionTruth | None:
        if not matches:
            return None
        if len(matches) != 1:
            raise PaymentProviderError(
                "Paymob reconciliation returned ambiguous transaction identity.",
                retryable=False,
            )
        return matches[0]

    @classmethod
    def _inquiry_collection(cls, response: httpx.Response) -> list[object]:
        body = cls._inquiry_json(response)
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get("results"), list):
            return cast(list[object], body["results"])
        raise PaymentProviderError(
            "Paymob returned malformed reconciliation collection data.",
            retryable=False,
        )

    @staticmethod
    def _inquiry_body(response: httpx.Response) -> dict[str, Any]:
        body = PaymobPaymentProvider._inquiry_json(response)
        if not isinstance(body, dict):
            raise PaymentProviderError(
                "Paymob returned malformed reconciliation data.", retryable=False
            )
        return body

    @staticmethod
    def _inquiry_json(response: httpx.Response) -> object:
        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise PaymentProviderError(
                "Paymob reconciliation is temporarily unavailable.", retryable=True
            )
        if not response.is_success:
            raise PaymentProviderError(
                "Paymob rejected the reconciliation inquiry.", retryable=False
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise PaymentProviderError(
                "Paymob returned invalid reconciliation data.", retryable=True
            ) from exc
        return body

    @staticmethod
    def _transaction_reference(obj: dict[str, Any]) -> UUID | None:
        order = obj.get("order")
        value = (
            order.get("merchant_order_id") if isinstance(order, dict) else None
        ) or obj.get("special_reference")
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    def _transaction_truth(
        self,
        obj: dict[str, Any],
        *,
        target: ProviderReconciliationTarget,
    ) -> ProviderTransactionTruth:
        raw_id = obj.get("id")
        amount_value = obj.get("amount", obj.get("amount_cents"))
        currency = obj.get("currency")
        integration_id = self._integer(obj.get("integration_id"))
        owner = self._integer(obj.get("owner"))
        source_type = self._source_type(obj)
        is_live = obj.get("is_live")
        occurred_at, provider_timestamp, timestamp_confidence = (
            _provider_timestamp_evidence(obj)
        )
        order = obj.get("order")
        order_id = order.get("id") if isinstance(order, dict) else order
        merchant_reference = (
            order.get("merchant_order_id") if isinstance(order, dict) else None
        ) or obj.get("special_reference")
        if not isinstance(amount_value, (str, int)) or isinstance(amount_value, bool):
            raise PaymentProviderError(
                "Paymob returned invalid reconciliation transaction data.",
                retryable=False,
            )
        try:
            payment_reference = UUID(str(merchant_reference))
            amount_minor = int(amount_value)
        except (TypeError, ValueError) as exc:
            raise PaymentProviderError(
                "Paymob returned invalid reconciliation transaction data.",
                retryable=False,
            ) from exc
        if (
            raw_id is None
            or not isinstance(currency, str)
            or integration_id is None
            or integration_id != self._configuration.integration_id
            or not isinstance(is_live, bool)
            or is_live == self._configuration.sandbox_mode
            or (
                self._configuration.expected_callback_owner is not None
                and owner != self._configuration.expected_callback_owner
            )
            or source_type not in self._configuration.supported_source_types
            or provider_timestamp is None
            or not isinstance(obj.get("success"), bool)
            or not isinstance(obj.get("pending"), bool)
            or order_id is None
            or payment_reference != target.payment_reference
            or (
                target.provider_payment_id is not None
                and str(raw_id) != target.provider_payment_id
            )
            or (
                target.provider_order_id is not None
                and str(order_id) != target.provider_order_id
            )
        ):
            raise PaymentProviderError(
                "Paymob reconciliation transaction identity did not match.",
                retryable=False,
            )
        decision, _state, _event_type = self._decision(obj)
        return ProviderTransactionTruth(
            provider_payment_id=str(raw_id),
            payment_reference=payment_reference,
            amount_minor=amount_minor,
            currency=currency.upper(),
            decision=decision,
            integration_id=integration_id,
            environment="live" if is_live else "sandbox",
            occurred_at=occurred_at,
            merchant_id=str(owner) if owner is not None else None,
            provider_order_id=str(order_id),
            source_type=source_type,
            provider_timestamp=provider_timestamp,
            provider_timestamp_confidence=timestamp_confidence,
        )

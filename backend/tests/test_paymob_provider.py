"""Contract tests for the isolated Paymob hosted-checkout adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from app.billing.providers import (
    CheckoutRequest,
    PaymentProviderConfigurationError,
    PaymentProviderError,
    PaymentProviderSignatureError,
    ProviderReconciliationTarget,
)
from app.billing.providers.paymob import (
    PaymobConfiguration,
    PaymobPaymentProvider,
    calculate_transaction_hmac,
)
from app.config.settings import Settings
from pydantic import ValidationError


def _configuration() -> PaymobConfiguration:
    return PaymobConfiguration(
        api_key="api-key-contract",
        secret_key="sk_test_contract",
        public_key="pk_test_contract",
        hmac_secret="contract-hmac-secret",
        integration_id=123456,
        expected_callback_owner=700001,
        base_url="https://accept.paymob.com",
        webhook_url="https://api.example.com/billing/webhooks/paymob",
        success_url="https://app.example.com/settings/billing/return",
        failure_url="https://app.example.com/settings/billing/return",
        currency="EGP",
        sandbox_mode=True,
        timeout_seconds=1,
        allowed_checkout_hosts=("accept.paymob.com",),
        supported_source_types=("card",),
    )


def _checkout_request(*, currency: str = "EGP") -> CheckoutRequest:
    return CheckoutRequest(
        reference=uuid4(),
        plan_code="professional",
        plan_name="Professional",
        amount_minor=500_000,
        currency=currency,
        email="owner@example.com",
        first_name="Factory",
        last_name="Owner",
        phone_number="+201001234567",
        city="Cairo",
        country="EG",
        street="Industrial Zone",
    )


def _transaction_object(**overrides: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "amount_cents": 500_000,
        "created_at": "2026-07-28T09:00:00Z",
        "currency": "EGP",
        "error_occured": False,
        "has_parent_transaction": False,
        "id": 900001,
        "integration_id": 123456,
        "is_3d_secure": True,
        "is_auth": False,
        "is_capture": False,
        "is_live": False,
        "is_refunded": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "order": {"id": 800001, "merchant_order_id": str(uuid4())},
        "owner": 700001,
        "pending": False,
        "source_data": {
            "pan": "2346",
            "sub_type": "MasterCard",
            "type": "card",
        },
        "success": True,
        "data": {"message": "Approved"},
    }
    obj.update(overrides)
    return obj


@pytest.mark.anyio
async def test_create_checkout_uses_current_intention_contract_and_hosted_ui() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": "pi_test_123",
                "intention_order_id": "order_test_123",
                "client_secret": "client_secret_test",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = PaymobPaymentProvider(_configuration(), client=client)
        request = _checkout_request()
        checkout = await provider.create_checkout(request)

    assert captured["url"] == "https://accept.paymob.com/v1/intention/"
    assert captured["authorization"] == "Token sk_test_contract"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["amount"] == 500_000
    assert payload["currency"] == "EGP"
    assert payload["items"] == [
        {
            "name": "Professional",
            "amount": 500_000,
            "description": "professional prepaid access period",
            "quantity": 1,
        }
    ]
    assert payload["payment_methods"] == [123456]
    assert payload["special_reference"] == str(request.reference)
    assert "card" not in json.dumps(payload).lower()
    assert checkout.provider_checkout_id == "pi_test_123"
    assert checkout.provider_order_id == "order_test_123"
    assert checkout.checkout_url.startswith(
        "https://accept.paymob.com/unifiedcheckout/?"
    )
    assert "publicKey=pk_test_contract" in checkout.checkout_url
    assert "clientSecret=client_secret_test" in checkout.checkout_url


@pytest.mark.anyio
async def test_reconciliation_uses_legacy_auth_token_and_exact_transaction() -> None:
    transaction = _transaction_object()
    reference = uuid4()
    transaction["order"] = {
        "id": 800001,
        "merchant_order_id": str(reference),
    }
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/api/auth/tokens":
            assert json.loads(request.content) == {"api_key": "api-key-contract"}
            return httpx.Response(201, json={"token": "short-lived-token"})
        assert request.url.path == "/api/acceptance/transactions/900001"
        assert request.url.params.get("token") == "short-lived-token"
        assert request.headers.get("Authorization") is None
        return httpx.Response(200, json=transaction)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        truth = await PaymobPaymentProvider(
            _configuration(), client=client
        ).reconcile_transaction(
            ProviderReconciliationTarget(
                payment_reference=reference,
                provider_payment_id="900001",
                provider_order_id="800001",
            )
        )

    assert truth is not None
    assert truth.payment_reference == reference
    assert truth.amount_minor == 500_000
    assert truth.currency == "EGP"
    assert truth.integration_id == 123456
    assert truth.environment == "sandbox"
    assert truth.merchant_id == "700001"
    assert truth.provider_order_id == "800001"
    assert len(captured) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("timestamps", "confidence", "expected_time"),
    [
        (
            {"created_at": "2026-08-09T06:57:00Z"},
            "explicit",
            "2026-08-09T06:57:00+00:00",
        ),
        (
            {"created_at": "2026-08-09T09:57:00+03:00"},
            "explicit",
            "2026-08-09T06:57:00+00:00",
        ),
        (
            {"created_at": "2026-08-09T01:57:00-05:00"},
            "explicit",
            "2026-08-09T06:57:00+00:00",
        ),
        ({"created_at": "2026-08-09T06:57:00"}, "ambiguous", None),
        ({"updated_at": "2026-08-09T06:58:00"}, "ambiguous", None),
        ({"paid_at": "2026-08-09T06:57:30"}, "ambiguous", None),
        (
            {
                "created_at": "2026-08-09T06:57:00",
                "updated_at": "2026-08-09T06:58:00",
                "paid_at": "2026-08-09T06:57:30",
            },
            "ambiguous",
            None,
        ),
    ],
)
async def test_reconciliation_timestamp_confidence_is_non_binding(
    timestamps: dict[str, str],
    confidence: str,
    expected_time: str | None,
) -> None:
    reference = uuid4()
    transaction = _transaction_object()
    for field in ("created_at", "updated_at", "paid_at"):
        transaction.pop(field, None)
    transaction.update(timestamps)
    transaction["order"] = {"id": 800001, "merchant_order_id": str(reference)}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(201, json={"token": "short-lived-token"})
        return httpx.Response(200, json=transaction)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        truth = await PaymobPaymentProvider(
            _configuration(), client=client
        ).reconcile_transaction(
            ProviderReconciliationTarget(
                payment_reference=reference,
                provider_payment_id="900001",
                provider_order_id="800001",
            )
        )

    assert truth is not None
    assert truth.provider_timestamp_confidence == confidence
    assert (
        truth.occurred_at.isoformat() if truth.occurred_at is not None else None
    ) == expected_time
    assert truth.provider_timestamp in timestamps.values()
    assert truth.decision == "succeeded_eligible"


@pytest.mark.anyio
async def test_reconciliation_requires_timestamp_and_authoritative_status_fields() -> (
    None
):
    reference = uuid4()
    transaction = _transaction_object()
    transaction["order"] = {"id": 800001, "merchant_order_id": str(reference)}

    async def rejected(candidate: dict[str, object]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/tokens":
                return httpx.Response(201, json={"token": "short-lived-token"})
            return httpx.Response(200, json=candidate)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(PaymentProviderError, match="identity"):
                await PaymobPaymentProvider(
                    _configuration(), client=client
                ).reconcile_transaction(
                    ProviderReconciliationTarget(
                        payment_reference=reference,
                        provider_payment_id="900001",
                        provider_order_id="800001",
                    )
                )

    missing_timestamp = dict(transaction)
    missing_timestamp.pop("created_at")
    await rejected(missing_timestamp)
    for field in ("success", "pending"):
        missing_status = dict(transaction)
        missing_status.pop(field)
        await rejected(missing_status)


@pytest.mark.anyio
async def test_reconciliation_uses_persisted_order_when_webhook_was_lost() -> None:
    transaction = _transaction_object()
    reference = uuid4()
    transaction["order"] = 800001

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(201, json={"token": "short-lived-token"})
        assert request.url.path == "/api/ecommerce/orders/800001"
        assert request.url.params.get("token") == "short-lived-token"
        return httpx.Response(
            200,
            json={
                "id": 800001,
                "merchant_order_id": str(reference),
                "transactions": [transaction],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        truth = await PaymobPaymentProvider(
            _configuration(), client=client
        ).reconcile_transaction(
            ProviderReconciliationTarget(
                payment_reference=reference,
                provider_order_id="800001",
            )
        )

    assert truth is not None
    assert truth.payment_reference == reference
    assert truth.provider_payment_id == "900001"
    assert truth.provider_order_id == "800001"


@pytest.mark.anyio
async def test_reconciliation_finds_provider_timeout_by_exact_merchant_reference() -> (
    None
):
    reference = uuid4()
    matching = _transaction_object()
    matching["order"] = {
        "id": 800001,
        "merchant_order_id": str(reference),
    }
    unrelated = _transaction_object(id=900002)
    unrelated["order"] = {
        "id": 800002,
        "merchant_order_id": str(uuid4()),
    }
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(201, json={"token": "short-lived-token"})
        assert request.url.path == "/api/acceptance/transactions"
        assert request.url.params.get("token") == "short-lived-token"
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(
            200,
            json={"results": [unrelated, matching] if page == 1 else []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        truth = await PaymobPaymentProvider(
            _configuration(), client=client
        ).reconcile_transaction(
            ProviderReconciliationTarget(payment_reference=reference)
        )

    assert truth is not None
    assert truth.payment_reference == reference
    assert truth.provider_payment_id == "900001"
    assert pages == [1, 2]


@pytest.mark.anyio
async def test_reconciliation_rejects_ambiguous_merchant_reference_matches() -> None:
    reference = uuid4()
    first = _transaction_object()
    first["order"] = {"id": 800001, "merchant_order_id": str(reference)}
    second = _transaction_object(id=900002)
    second["order"] = {"id": 800002, "merchant_order_id": str(reference)}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(201, json={"token": "short-lived-token"})
        return httpx.Response(200, json={"results": [first, second]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PaymentProviderError, match="ambiguous"):
            await PaymobPaymentProvider(
                _configuration(), client=client
            ).reconcile_transaction(
                ProviderReconciliationTarget(payment_reference=reference)
            )


@pytest.mark.anyio
async def test_reconciliation_requires_api_key_before_network() -> None:
    configuration = _configuration()
    provider = PaymobPaymentProvider(replace(configuration, api_key=None))
    with pytest.raises(PaymentProviderConfigurationError, match="API key"):
        await provider.reconcile_transaction(
            ProviderReconciliationTarget(
                payment_reference=uuid4(), provider_payment_id="900001"
            )
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mismatch",
    ["reference", "owner", "integration", "environment", "order"],
)
async def test_reconciliation_identity_mismatch_fails_closed_without_secrets(
    mismatch: str,
) -> None:
    target_reference = uuid4()
    transaction = _transaction_object()
    transaction["order"] = {
        "id": 800001,
        "merchant_order_id": str(target_reference),
    }
    if mismatch == "reference":
        transaction["order"] = {
            "id": 800001,
            "merchant_order_id": str(uuid4()),
        }
    elif mismatch == "owner":
        transaction["owner"] = 700002
    elif mismatch == "integration":
        transaction["integration_id"] = 123457
    elif mismatch == "environment":
        transaction["is_live"] = True
    elif mismatch == "order":
        transaction["order"] = {
            "id": 800002,
            "merchant_order_id": str(target_reference),
        }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(201, json={"token": "short-lived-token"})
        return httpx.Response(200, json=transaction)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PaymentProviderError, match="identity") as raised:
            await PaymobPaymentProvider(
                _configuration(), client=client
            ).reconcile_transaction(
                ProviderReconciliationTarget(
                    payment_reference=target_reference,
                    provider_payment_id="900001",
                    provider_order_id="800001",
                )
            )
    safe_error = str(raised.value)
    assert "api-key-contract" not in safe_error
    assert "short-lived-token" not in safe_error


@pytest.mark.anyio
async def test_create_checkout_rejects_incorrect_currency_before_network() -> None:
    provider = PaymobPaymentProvider(_configuration())
    with pytest.raises(PaymentProviderError, match="currency") as raised:
        await provider.create_checkout(_checkout_request(currency="USD"))
    assert raised.value.retryable is False


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
async def test_retryable_provider_responses_are_classified(status_code: int) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, json={"detail": "temporary"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PaymobPaymentProvider(_configuration(), client=client)
        with pytest.raises(PaymentProviderError) as raised:
            await provider.create_checkout(_checkout_request())
    assert raised.value.retryable is True


@pytest.mark.anyio
async def test_provider_timeout_is_retryable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        provider = PaymobPaymentProvider(_configuration(), client=client)
        with pytest.raises(PaymentProviderError) as raised:
            await provider.create_checkout(_checkout_request())
    assert raised.value.retryable is True


def test_valid_success_webhook_is_verified_and_normalized() -> None:
    provider = PaymobPaymentProvider(_configuration())
    obj = _transaction_object()
    signature = calculate_transaction_hmac(obj, "contract-hmac-secret")

    event = provider.parse_webhook(
        {"type": "TRANSACTION", "obj": obj}, signature=signature
    )

    assert event.raw_provider_event_id == "900001"
    assert event.provider_event_id.startswith(
        "transaction:900001:transaction.captured:"
    )
    assert event.state == "succeeded"
    assert event.decision == "succeeded_eligible"
    assert event.amount_minor == 500_000
    assert event.currency == "EGP"


def test_webhook_timestamp_without_offset_is_treated_as_ambiguous() -> None:
    provider = PaymobPaymentProvider(_configuration())
    obj = _transaction_object(created_at="2026-07-28T09:00:00")
    signature = calculate_transaction_hmac(obj, "contract-hmac-secret")

    event = provider.parse_webhook(
        {"type": "TRANSACTION", "obj": obj}, signature=signature
    )

    assert event.occurred_at is None


def test_transaction_hmac_uses_paymob_documented_field_order() -> None:
    obj = _transaction_object()
    canonical = "".join(
        (
            "500000",
            "2026-07-28T09:00:00Z",
            "EGP",
            "false",
            "false",
            "900001",
            "123456",
            "true",
            "false",
            "false",
            "false",
            "true",
            "false",
            "800001",
            "700001",
            "false",
            "2346",
            "MasterCard",
            "card",
            "true",
        )
    )
    expected = hmac.new(
        b"contract-hmac-secret", canonical.encode(), hashlib.sha512
    ).hexdigest()
    assert calculate_transaction_hmac(obj, "contract-hmac-secret") == expected


def test_invalid_signature_is_rejected() -> None:
    provider = PaymobPaymentProvider(_configuration())
    with pytest.raises(PaymentProviderSignatureError):
        provider.parse_webhook(
            {"type": "TRANSACTION", "obj": _transaction_object()},
            signature="0" * 128,
        )


@pytest.mark.parametrize(
    ("overrides", "state", "event_type"),
    [
        ({"success": False}, "failed", "transaction.failed"),
        ({"is_refunded": True}, "refunded", "transaction.refunded"),
        ({"is_voided": True}, "reversed", "transaction.reversed"),
        ({"pending": True, "success": False}, "pending", "transaction.pending"),
    ],
)
def test_callback_states_are_normalized(
    overrides: dict[str, object], state: str, event_type: str
) -> None:
    provider = PaymobPaymentProvider(_configuration())
    obj = _transaction_object(**overrides)
    event = provider.parse_webhook(
        {"type": "TRANSACTION", "obj": obj},
        signature=calculate_transaction_hmac(obj, "contract-hmac-secret"),
    )
    assert event.state == state
    assert event.event_type == event_type


def test_unknown_callback_type_is_rejected() -> None:
    provider = PaymobPaymentProvider(_configuration())
    with pytest.raises(PaymentProviderError, match="not supported"):
        provider.parse_webhook(
            {"type": "TOKEN", "obj": _transaction_object()},
            signature="0" * 128,
        )


def test_paymob_configuration_requires_complete_environment_and_key_mode(
    settings: Settings,
) -> None:
    values = settings.model_dump()
    values["payment_provider"] = "paymob"
    with pytest.raises(ValidationError, match="configuration is incomplete"):
        Settings.model_validate(values)

    values.update(
        {
            "paymob_secret_key": "sk_test_contract",
            "paymob_public_key": "pk_test_contract",
            "paymob_hmac_secret": "hmac-contract",
            "paymob_integration_id": 123456,
            "paymob_expected_callback_owner": 700001,
            "paymob_webhook_url": "https://api.example.com/billing/webhooks/paymob",
            "payment_success_url": "https://app.example.com/settings/billing/return",
            "payment_failure_url": "https://app.example.com/settings/billing/return",
            "payment_sandbox_mode": False,
        }
    )
    with pytest.raises(ValidationError, match="Test Paymob keys"):
        Settings.model_validate(values)

    values.update(
        {
            "paymob_secret_key": "sk_live_contract",
            "paymob_public_key": "pk_live_contract",
            "payment_sandbox_mode": True,
        }
    )
    with pytest.raises(ValidationError, match="Live Paymob keys"):
        Settings.model_validate(values)


def test_production_rejects_any_enabled_payment_provider(settings: Settings) -> None:
    values = settings.model_dump()
    values.update(
        {
            "environment": "production",
            "enable_api_docs": False,
            "allowed_hosts": ("api.example.com",),
            "cors_allowed_origins": ("https://app.example.com",),
            "app_base_url": "https://app.example.com",
            "api_base_url": "https://api.example.com",
            "cookie_secure": True,
            "email_verification_required": True,
            "email_provider": "smtp",
            "email_from": "accounts@example.com",
            "smtp_host": "smtp.example.com",
            "payment_provider": "paymob",
            "paymob_secret_key": "sk_test_contract",
            "paymob_public_key": "pk_test_contract",
            "paymob_hmac_secret": "hmac-contract",
            "paymob_integration_id": 123456,
            "paymob_expected_callback_owner": 700001,
            "paymob_webhook_url": "https://api.example.com/billing/webhooks/paymob",
            "payment_success_url": "https://app.example.com/settings/billing/return",
            "payment_failure_url": "https://app.example.com/settings/billing/return",
            "payment_sandbox_mode": True,
        }
    )
    with pytest.raises(ValidationError, match="must remain disabled in production"):
        Settings.model_validate(values)


def test_expected_callback_owner_uses_canonical_name_with_legacy_fallback(
    settings: Settings,
) -> None:
    values = settings.model_dump()
    values.pop("paymob_expected_callback_owner", None)

    legacy = Settings.model_validate({**values, "PAYMOB_MERCHANT_ID": 700001})
    assert legacy.paymob_expected_callback_owner == 700001

    canonical = Settings.model_validate(
        {**values, "PAYMOB_EXPECTED_CALLBACK_OWNER": 700002}
    )
    assert canonical.paymob_expected_callback_owner == 700002

    both = Settings.model_validate(
        {
            **values,
            "PAYMOB_EXPECTED_CALLBACK_OWNER": 700002,
            "PAYMOB_MERCHANT_ID": 700001,
        }
    )
    assert both.paymob_expected_callback_owner == 700002

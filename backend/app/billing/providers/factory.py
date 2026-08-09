"""Configured payment-provider construction."""

from app.billing.providers.base import (
    PaymentProvider,
    PaymentProviderConfigurationError,
)
from app.billing.providers.paymob import PaymobConfiguration, PaymobPaymentProvider
from app.config.settings import Settings


def configured_payment_provider(settings: Settings) -> PaymentProvider:
    """Return the explicitly selected provider; never emulate payment success."""
    if settings.payment_provider != "paymob":
        raise PaymentProviderConfigurationError(
            "A real payment provider is not configured."
        )
    if (
        settings.paymob_secret_key is None
        or settings.paymob_public_key is None
        or settings.paymob_hmac_secret is None
        or settings.paymob_integration_id is None
        or settings.paymob_expected_callback_owner is None
        or settings.paymob_webhook_url is None
        or settings.payment_success_url is None
        or settings.payment_failure_url is None
    ):
        raise PaymentProviderConfigurationError("Paymob configuration is incomplete.")
    return PaymobPaymentProvider(
        PaymobConfiguration(
            api_key=(
                settings.paymob_api_key.get_secret_value()
                if settings.paymob_api_key is not None
                else None
            ),
            secret_key=settings.paymob_secret_key.get_secret_value(),
            public_key=settings.paymob_public_key.get_secret_value(),
            hmac_secret=settings.paymob_hmac_secret.get_secret_value(),
            integration_id=settings.paymob_integration_id,
            expected_callback_owner=settings.paymob_expected_callback_owner,
            base_url=settings.paymob_base_url,
            webhook_url=settings.paymob_webhook_url,
            success_url=settings.payment_success_url,
            failure_url=settings.payment_failure_url,
            currency=settings.payment_currency,
            sandbox_mode=settings.payment_sandbox_mode,
            timeout_seconds=settings.payment_http_timeout_seconds,
            allowed_checkout_hosts=settings.paymob_allowed_checkout_hosts,
            supported_source_types=settings.paymob_supported_source_types,
        )
    )

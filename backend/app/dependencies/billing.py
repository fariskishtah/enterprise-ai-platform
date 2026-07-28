"""Payment-provider and billing queue dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.billing.providers import (
    PaymentProvider,
    PaymentProviderConfigurationError,
    configured_payment_provider,
)
from app.billing.queue import BillingWebhookQueue, DramatiqBillingWebhookQueue
from app.config.settings import Settings, get_settings


def get_payment_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaymentProvider:
    try:
        return configured_payment_provider(settings)
    except PaymentProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def get_billing_webhook_queue() -> BillingWebhookQueue:
    return DramatiqBillingWebhookQueue()

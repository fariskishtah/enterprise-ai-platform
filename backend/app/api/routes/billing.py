"""Billing catalogue, hosted checkout, and authenticated provider callbacks."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.catalog import PLAN_CATALOG
from app.billing.providers import (
    PaymentProvider,
    PaymentProviderConfigurationError,
    PaymentProviderError,
    PaymentProviderSignatureError,
)
from app.billing.queue import BillingWebhookQueue
from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_permissions
from app.dependencies.billing import get_billing_webhook_queue, get_payment_provider
from app.dependencies.database import get_db_session
from app.models.user import User
from app.permissions import Permission
from app.repositories.billing import BillingRepository
from app.schemas.billing import (
    CheckoutCreateRequest,
    CheckoutResponse,
    PaymentStatusResponse,
    PlanListResponse,
    PlanResponse,
    WebhookAcceptedResponse,
)
from app.services.billing import (
    BillingConflictError,
    BillingDetails,
    BillingNotFoundError,
    BillingService,
    BillingWebhookPayloadError,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=PlanListResponse)
async def list_plans() -> PlanListResponse:
    """Return the backend-authoritative active plan catalogue."""
    return PlanListResponse(
        items=[
            PlanResponse(
                code=plan.code,
                name=plan.name,
                monthly_price_minor=plan.monthly_price_minor,
                currency=plan.currency,
                description=plan.description,
                entitlements=plan.entitlements,
            )
            for plan in PLAN_CATALOG
        ]
    )


@router.post(
    "/checkouts",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_checkout(
    payload: CheckoutCreateRequest,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=16,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CheckoutResponse:
    """Create or replay one backend-priced Paymob hosted checkout."""
    service = BillingService(session, provider)
    try:
        result = await service.create_checkout(
            actor=actor,
            plan_code=payload.plan_code,
            billing_details=BillingDetails(**payload.billing_details.model_dump()),
            idempotency_key=idempotency_key,
        )
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except PaymentProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except PaymentProviderError as exc:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.retryable
            else status.HTTP_502_BAD_GATEWAY
        )
        headers = {"Retry-After": "5"} if exc.retryable else None
        raise HTTPException(
            status_code=response_status, detail=str(exc), headers=headers
        ) from exc
    return CheckoutResponse(
        payment_id=result.payment_id,
        provider=provider.name,
        provider_checkout_id=result.checkout.provider_checkout_id,
        checkout_url=result.checkout.checkout_url,
        plan_code=result.plan.code,
        amount_minor=result.plan.monthly_price_minor,
        currency=result.plan.currency,
        status=result.status,
        reused=result.reused,
        failure_url=settings.payment_failure_url or "",
    )


@router.get("/payments/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(
    payment_id: UUID,
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PaymentStatusResponse:
    payment = await BillingRepository(session).get_company_payment(
        payment_id, actor.company_id
    )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The payment does not exist."
        )
    return PaymentStatusResponse(
        payment_id=payment.id,
        plan_code=payment.plan_code,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        status=payment.status,
        failure_code=payment.failure_code,
    )


@router.post("/payments/{payment_id}/cancel", response_model=PaymentStatusResponse)
async def cancel_checkout(
    payment_id: UUID,
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
) -> PaymentStatusResponse:
    """Record explicit hosted-checkout abandonment without claiming provider success."""
    try:
        payment = await BillingService(session, provider).cancel_checkout(
            actor=actor, payment_id=payment_id
        )
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return PaymentStatusResponse(
        payment_id=payment.id,
        plan_code=payment.plan_code,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        status=payment.status,
        failure_code=payment.failure_code,
    )


@router.post(
    "/webhooks/paymob",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def paymob_webhook(
    payload: Annotated[dict[str, object], Body()],
    signature: Annotated[str, Query(alias="hmac")],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
    queue: Annotated[BillingWebhookQueue, Depends(get_billing_webhook_queue)],
) -> WebhookAcceptedResponse:
    """Authenticate, durably deduplicate, and queue a Paymob callback."""
    service = BillingService(session, provider)
    try:
        result = await service.ingest_webhook(payload, signature=signature)
    except PaymentProviderSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except (PaymentProviderError, BillingWebhookPayloadError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if result.should_enqueue:
        try:
            queue.enqueue(result.event_id)
        except Exception as exc:
            await service.release_failed_enqueue(result.event_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The callback was saved but could not be queued.",
                headers={"Retry-After": "5"},
            ) from exc
    return WebhookAcceptedResponse(duplicate=result.duplicate)

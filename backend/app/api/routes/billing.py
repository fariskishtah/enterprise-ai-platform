"""Billing catalogue, hosted checkout, and authenticated provider callbacks."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)
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
from app.dependencies.entitlements import get_entitlement_service
from app.models.billing import Payment, Subscription
from app.models.user import User
from app.permissions import Permission
from app.repositories.billing import BillingRepository
from app.schemas.billing import (
    BillingAuditEventResponse,
    BillingAuditHistoryResponse,
    BillingProviderEventHistoryResponse,
    BillingProviderEventResponse,
    BillingReasonRequest,
    CheckoutCreateRequest,
    CheckoutResponse,
    EntitlementItemResponse,
    EntitlementOverrideRequest,
    EntitlementOverrideResponse,
    EntitlementSnapshotResponse,
    InvoiceHistoryResponse,
    InvoiceReferenceResponse,
    PaymentHistoryResponse,
    PaymentStatusResponse,
    PlanListResponse,
    PlanResponse,
    SubscriptionCancelRequest,
    SubscriptionEnvelope,
    SubscriptionResponse,
    UpgradeRecommendationResponse,
    WebhookAcceptedResponse,
    WebhookReplayResponse,
)
from app.services.billing import (
    BillingConflictError,
    BillingDetails,
    BillingError,
    BillingNotFoundError,
    BillingPolicy,
    BillingService,
    BillingWebhookPayloadError,
    CheckoutResult,
)
from app.services.entitlements import EntitlementOverrideError, EntitlementService

router = APIRouter(prefix="/billing", tags=["billing"])


def _error_detail(exc: BillingError) -> dict[str, str]:
    return {"code": exc.code, "message": str(exc)}


def _service(
    session: AsyncSession,
    provider: PaymentProvider | None = None,
    settings: Settings | None = None,
) -> BillingService:
    policy = (
        BillingPolicy(
            grace_period_days=settings.billing_grace_period_days,
            incomplete_expiry_hours=settings.billing_incomplete_expiry_hours,
            suspension_expiry_days=settings.billing_suspension_expiry_days,
        )
        if settings is not None
        else None
    )
    return BillingService(session, provider, policy=policy)


def _payment_response(payment: Payment) -> PaymentStatusResponse:
    return PaymentStatusResponse(
        payment_id=payment.id,
        plan_code=payment.plan_code,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        status=payment.status,
        failure_code=payment.failure_code,
        purpose=payment.purpose,
        provider=payment.provider,
        provider_payment_id=payment.provider_payment_id,
        provider_checkout_id=payment.provider_checkout_id,
        provider_occurred_at=payment.provider_occurred_at,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


def _checkout_response(
    result: CheckoutResult, provider: PaymentProvider, settings: Settings
) -> CheckoutResponse:
    return CheckoutResponse(
        payment_id=result.payment_id,
        subscription_id=result.subscription_id,
        provider=provider.name,
        provider_checkout_id=result.checkout.provider_checkout_id,
        checkout_url=result.checkout.checkout_url,
        plan_code=result.plan.code,
        amount_minor=result.plan.monthly_price_minor,
        currency=result.plan.currency,
        status=result.status,
        reused=result.reused,
        purpose=result.purpose,
        failure_url=settings.payment_failure_url or "",
    )


async def _subscription_response(
    repository: BillingRepository, subscription: Subscription
) -> SubscriptionResponse:
    plan = await repository.get_plan_by_id(subscription.plan_id)
    pending = (
        await repository.get_plan_by_id(subscription.pending_plan_id)
        if subscription.pending_plan_id
        else None
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "subscription_plan_missing", "message": "Plan missing."},
        )
    actions: list[str] = []
    if subscription.status in {"trialing", "active", "past_due"}:
        actions.extend(["upgrade", "downgrade", "cancel"])
        if subscription.cancel_at_period_end:
            actions.append("reactivate")
    elif subscription.status in {"cancelled", "expired", "suspended"}:
        actions.append("checkout_to_reactivate")
    elif subscription.status == "incomplete":
        actions.append("complete_checkout")
    return SubscriptionResponse(
        subscription_id=subscription.id,
        status=subscription.status,
        plan_code=plan.code,
        pending_plan_code=pending.code if pending else None,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        grace_period_ends_at=subscription.grace_period_ends_at,
        cancel_at_period_end=subscription.cancel_at_period_end,
        suspended_at=subscription.suspended_at,
        ended_at=subscription.ended_at,
        version=subscription.version,
        allowed_actions=actions,
    )


async def _entitlement_response(
    service: EntitlementService, company_id: UUID
) -> EntitlementSnapshotResponse:
    snapshot = await service.snapshot(company_id)
    return EntitlementSnapshotResponse(
        subscription_status=snapshot.subscription_status,
        access_mode=snapshot.access_mode,
        plan_code=snapshot.plan_code,
        items=[
            EntitlementItemResponse(
                key=item.key,
                enabled=item.enabled,
                limit=item.limit,
                used=item.used,
                remaining=item.remaining,
                over_limit=item.over_limit,
                source=item.source,
                period_start=(
                    item.period_start.isoformat() if item.period_start else None
                ),
                period_end=item.period_end.isoformat() if item.period_end else None,
            )
            for item in snapshot.items
        ],
        recommended_plan=snapshot.recommended_plan,
    )


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
    service = _service(session, provider, settings)
    try:
        result = await service.create_checkout(
            actor=actor,
            plan_code=payload.plan_code,
            billing_details=BillingDetails(**payload.billing_details.model_dump()),
            idempotency_key=idempotency_key,
        )
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_error_detail(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_error_detail(exc)
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
    return _checkout_response(result, provider, settings)


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
    return _payment_response(payment)


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
            status_code=status.HTTP_404_NOT_FOUND, detail=_error_detail(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_error_detail(exc)
        ) from exc
    return _payment_response(payment)


@router.get("/subscription", response_model=SubscriptionEnvelope)
async def get_current_subscription(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SubscriptionEnvelope:
    subscription = await _service(session, settings=settings).current_subscription(
        actor=actor
    )
    if subscription is None:
        return SubscriptionEnvelope(item=None)
    return SubscriptionEnvelope(
        item=await _subscription_response(BillingRepository(session), subscription)
    )


async def _change_plan(
    *,
    direction: str,
    payload: CheckoutCreateRequest,
    idempotency_key: str,
    actor: User,
    session: AsyncSession,
    provider: PaymentProvider,
    settings: Settings,
) -> CheckoutResponse:
    try:
        result = await _service(session, provider, settings).create_checkout(
            actor=actor,
            plan_code=payload.plan_code,
            billing_details=BillingDetails(**payload.billing_details.model_dump()),
            idempotency_key=idempotency_key,
            expected_change="upgrade" if direction == "upgrade" else "downgrade",
        )
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_error_detail(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_error_detail(exc)
        ) from exc
    except PaymentProviderError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.retryable
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail={"code": "payment_provider_error", "message": str(exc)},
        ) from exc
    return _checkout_response(result, provider, settings)


@router.post(
    "/subscription/upgrade",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upgrade_subscription(
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
    return await _change_plan(
        direction="upgrade",
        payload=payload,
        idempotency_key=idempotency_key,
        actor=actor,
        session=session,
        provider=provider,
        settings=settings,
    )


@router.post(
    "/subscription/downgrade",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def downgrade_subscription(
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
    return await _change_plan(
        direction="downgrade",
        payload=payload,
        idempotency_key=idempotency_key,
        actor=actor,
        session=session,
        provider=provider,
        settings=settings,
    )


@router.post("/subscription/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    payload: SubscriptionCancelRequest,
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SubscriptionResponse:
    service = _service(session, settings=settings)
    try:
        subscription = await service.cancel_subscription(
            actor=actor, immediate=payload.mode == "immediate"
        )
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_error_detail(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_error_detail(exc)
        ) from exc
    return await _subscription_response(BillingRepository(session), subscription)


@router.post("/subscription/reactivate", response_model=SubscriptionResponse)
async def reactivate_subscription(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SubscriptionResponse:
    service = _service(session, settings=settings)
    try:
        subscription = await service.reactivate_subscription(actor=actor)
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_error_detail(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_error_detail(exc)
        ) from exc
    return await _subscription_response(BillingRepository(session), subscription)


@router.get("/history/payments", response_model=PaymentHistoryResponse)
async def list_payment_history(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaymentHistoryResponse:
    rows, total = await BillingRepository(session).list_company_payments(
        actor.company_id, offset=(page - 1) * page_size, limit=page_size
    )
    return PaymentHistoryResponse(
        items=[_payment_response(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/history/invoices", response_model=InvoiceHistoryResponse)
async def list_invoice_history(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> InvoiceHistoryResponse:
    rows, total = await BillingRepository(session).list_company_invoices(
        actor.company_id, offset=(page - 1) * page_size, limit=page_size
    )
    return InvoiceHistoryResponse(
        items=[
            InvoiceReferenceResponse(
                invoice_id=row.id,
                payment_id=row.payment_id,
                provider=row.provider,
                provider_invoice_id=row.provider_invoice_id,
                receipt_url=row.receipt_url,
                amount_minor=row.amount_minor,
                currency=row.currency,
                status=row.status,
                issued_at=row.issued_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/entitlements", response_model=EntitlementSnapshotResponse)
async def current_entitlements(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> EntitlementSnapshotResponse:
    return await _entitlement_response(entitlements, actor.company_id)


@router.get("/usage", response_model=EntitlementSnapshotResponse)
@router.get("/usage/breakdown", response_model=EntitlementSnapshotResponse)
@router.get("/limits", response_model=EntitlementSnapshotResponse)
async def current_usage_and_limits(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> EntitlementSnapshotResponse:
    return await _entitlement_response(entitlements, actor.company_id)


@router.get("/recommendation", response_model=UpgradeRecommendationResponse)
async def upgrade_recommendation(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> UpgradeRecommendationResponse:
    snapshot = await entitlements.snapshot(actor.company_id)
    return UpgradeRecommendationResponse(
        current_plan=snapshot.plan_code,
        recommended_plan=snapshot.recommended_plan,
        over_limit_entitlements=[
            item.key for item in snapshot.items if item.over_limit
        ],
    )


@router.get("/admin/usage", response_model=EntitlementSnapshotResponse)
async def admin_usage_inspection(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> EntitlementSnapshotResponse:
    return await _entitlement_response(entitlements, actor.company_id)


@router.put(
    "/platform/tenants/{company_id}/entitlement-overrides/{key}",
    response_model=EntitlementOverrideResponse,
)
async def set_entitlement_override(
    company_id: UUID,
    key: str,
    payload: EntitlementOverrideRequest,
    actor: Annotated[
        User,
        Depends(require_permissions(Permission.BILLING_PLATFORM_OPERATE)),
    ],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> EntitlementOverrideResponse:
    try:
        override = await entitlements.set_override(
            company_id=company_id,
            actor_user_id=actor.id,
            key=key,
            integer_limit=payload.integer_limit,
            enabled=payload.enabled,
            reason=payload.reason,
            expires_at=payload.expires_at,
        )
    except EntitlementOverrideError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.as_detail(),
        ) from exc
    return EntitlementOverrideResponse(
        override_id=override.id,
        key=override.key,
        integer_limit=override.integer_limit,
        enabled=override.enabled,
        reason=override.reason,
        expires_at=override.expires_at,
        created_by_user_id=override.created_by_user_id,
        created_at=override.created_at,
        updated_at=override.updated_at,
    )


@router.delete(
    "/platform/tenants/{company_id}/entitlement-overrides/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_entitlement_override(
    company_id: UUID,
    key: str,
    payload: BillingReasonRequest,
    actor: Annotated[
        User,
        Depends(require_permissions(Permission.BILLING_PLATFORM_OPERATE)),
    ],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> Response:
    try:
        deleted = await entitlements.delete_override(
            company_id=company_id,
            actor_user_id=actor.id,
            key=key,
            reason=payload.reason,
        )
    except EntitlementOverrideError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.as_detail(),
        ) from exc
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "override_not_found", "message": "Override not found."},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/events", response_model=BillingAuditHistoryResponse)
async def list_billing_events(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BillingAuditHistoryResponse:
    rows, total = await BillingRepository(session).list_company_audit_events(
        actor.company_id, offset=(page - 1) * page_size, limit=page_size
    )
    return BillingAuditHistoryResponse(
        items=[
            BillingAuditEventResponse(
                event_id=row.id,
                actor_user_id=row.actor_user_id,
                action=row.action,
                result=row.result,
                safe_metadata=row.safe_metadata,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/admin/provider-events", response_model=BillingProviderEventHistoryResponse
)
async def list_provider_events(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BillingProviderEventHistoryResponse:
    rows, total = await BillingRepository(session).list_company_webhook_events(
        actor.company_id, offset=(page - 1) * page_size, limit=page_size
    )
    return BillingProviderEventHistoryResponse(
        items=[
            BillingProviderEventResponse(
                event_id=row.id,
                provider=row.provider,
                provider_event_id=row.provider_event_id,
                event_type=row.event_type,
                status=row.status,
                attempts=row.attempts,
                last_error=row.last_error,
                last_error_category=row.last_error_category,
                received_at=row.received_at,
                queued_at=row.queued_at,
                processing_started_at=row.processing_started_at,
                next_retry_at=row.next_retry_at,
                processed_at=row.processed_at,
                dead_lettered_at=row.dead_lettered_at,
                replay_count=row.replay_count,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/platform/tenants/{company_id}/provider-events/{event_id}/replay",
    response_model=WebhookReplayResponse,
)
async def replay_provider_event(
    company_id: UUID,
    event_id: UUID,
    payload: BillingReasonRequest,
    actor: Annotated[
        User,
        Depends(require_permissions(Permission.BILLING_PLATFORM_OPERATE)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[BillingWebhookQueue, Depends(get_billing_webhook_queue)],
) -> WebhookReplayResponse:
    """Audit and republish one tenant-bound event without bypassing idempotency."""
    service = BillingService(session, None)
    try:
        event = await service.replay_webhook_event(
            actor=actor,
            company_id=company_id,
            event_id=event_id,
            reason=payload.reason,
        )
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_error_detail(exc)
        ) from exc
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_error_detail(exc)
        ) from exc
    try:
        queue.enqueue(event.id)
    except Exception as exc:
        await service.release_failed_enqueue(event.id, category="replay_queue_failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The replay was saved but could not be queued.",
            headers={"Retry-After": "5"},
        ) from exc
    return WebhookReplayResponse(
        event_id=event.id,
        queued=True,
        replay_count=event.replay_count,
    )


@router.post("/admin/subscription/reconcile", response_model=SubscriptionResponse)
async def reconcile_subscription(
    actor: Annotated[User, Depends(require_permissions(Permission.BILLING_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SubscriptionResponse:
    try:
        subscription = await _service(
            session, settings=settings
        ).reconcile_subscription(actor=actor)
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_error_detail(exc)
        ) from exc
    return await _subscription_response(BillingRepository(session), subscription)


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

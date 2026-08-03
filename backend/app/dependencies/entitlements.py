"""Entitlement service dependency and consistent quota error responses."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db_session
from app.models.user import User
from app.services.billing import BillingPolicy
from app.services.entitlements import EntitlementError, EntitlementService


def get_entitlement_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EntitlementService:
    return EntitlementService(
        session,
        enforced=settings.billing_entitlements_enforced,
        policy=BillingPolicy(
            grace_period_days=settings.billing_grace_period_days,
            incomplete_expiry_hours=settings.billing_incomplete_expiry_hours,
            suspension_expiry_days=settings.billing_suspension_expiry_days,
        ),
    )


def entitlement_http_error(exc: EntitlementError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=exc.as_detail(),
    )


async def require_model_training_entitlement(
    actor: Annotated[User, Depends(get_current_user)],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> None:
    try:
        await entitlements.require_feature(actor.company_id, "model_training")
        await entitlements.require_capacity(actor.company_id, "training_concurrency")
    except EntitlementError as exc:
        raise entitlement_http_error(exc) from exc


async def require_advanced_reports_entitlement(
    actor: Annotated[User, Depends(get_current_user)],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> None:
    try:
        await entitlements.require_feature(actor.company_id, "advanced_reports")
    except EntitlementError as exc:
        raise entitlement_http_error(exc) from exc

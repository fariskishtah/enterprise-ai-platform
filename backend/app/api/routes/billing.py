"""Billing catalogue routes.

Checkout and webhook mutations are intentionally not exposed until a configured
provider can create and verify real hosted-checkout sessions.
"""

from fastapi import APIRouter

from app.billing.catalog import PLAN_CATALOG
from app.schemas.billing import PlanListResponse, PlanResponse

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

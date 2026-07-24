"""Authenticated product-experience configuration routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config.settings import Settings, get_settings
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.product import ProductFeatureFlagsResponse

router = APIRouter(prefix="/product", tags=["product"])


@router.get("/features", response_model=ProductFeatureFlagsResponse)
async def get_product_features(
    _current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductFeatureFlagsResponse:
    """Return presentation-safe feature controls to an authenticated user."""
    return ProductFeatureFlagsResponse(
        simplified_experience_enabled=settings.simplified_experience_enabled,
        operations_workflow_enabled=settings.operations_workflow_enabled,
        demo_tools_enabled=settings.demo_tools_enabled,
    )

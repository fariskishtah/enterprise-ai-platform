"""Authenticated product-experience configuration routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.config.settings import Settings, get_settings
from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_public_demo_workspace_service
from app.models.user import User
from app.schemas.product import (
    ProductFeatureFlagsResponse,
    PublicDemoWorkspaceResponse,
)
from app.services.public_demo import (
    PublicDemoWorkspaceError,
    PublicDemoWorkspaceService,
)

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


@router.post(
    "/public-demo-workspace/prepare",
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=PublicDemoWorkspaceResponse,
)
async def prepare_public_demo_workspace(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        PublicDemoWorkspaceService,
        Depends(get_public_demo_workspace_service),
    ],
) -> PublicDemoWorkspaceResponse:
    """Idempotently prepare bounded synthetic assets for a public account."""
    try:
        result = await service.prepare(current_user)
    except PublicDemoWorkspaceError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return PublicDemoWorkspaceResponse(
        status=result.status,
        factory_count=result.factory_count,
        machine_count=result.machine_count,
        sensor_count=result.sensor_count,
        reading_count=result.reading_count,
    )

"""Factory routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies.auth import require_roles
from app.dependencies.services import get_manufacturing_service
from app.models.user import User, UserRole
from app.schemas.common import PaginatedResponse, SortOrder
from app.schemas.manufacturing import (
    FactoryCreate,
    FactoryResponse,
    FactorySortField,
    FactoryUpdate,
)
from app.services.exceptions import RelatedResourceNotFoundError, ResourceNotFoundError
from app.services.manufacturing import FactoryUpdateFields, ManufacturingService

router = APIRouter(prefix="/factories", tags=["factories"])


def _not_found(exc: ResourceNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _related_not_found(exc: RelatedResourceNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@router.get(
    "",
    response_model=PaginatedResponse[FactoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List factories",
)
async def list_factories(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    company_id: UUID | None = None,
    sort_by: FactorySortField = FactorySortField.CREATED_AT,
    sort_order: SortOrder = SortOrder.ASC,
) -> PaginatedResponse[FactoryResponse]:
    """List active factories with pagination, filtering, search, and sorting."""
    page = await service.list_factories(
        limit=limit,
        offset=offset,
        search=search,
        company_id=company_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[FactoryResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=FactoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a factory",
)
async def create_factory(
    payload: FactoryCreate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> FactoryResponse:
    """Create a factory."""
    try:
        factory = await service.create_factory(
            company_id=payload.company_id,
            name=payload.name,
            location=payload.location,
            description=payload.description,
        )
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    return FactoryResponse.model_validate(factory)


@router.get(
    "/{factory_id}",
    response_model=FactoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a factory",
)
async def get_factory(
    factory_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> FactoryResponse:
    """Return a factory by ID."""
    try:
        factory = await service.get_factory(factory_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return FactoryResponse.model_validate(factory)


@router.patch(
    "/{factory_id}",
    response_model=FactoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a factory",
)
async def update_factory(
    factory_id: UUID,
    payload: FactoryUpdate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> FactoryResponse:
    """Update a factory."""
    try:
        factory = await service.update_factory(
            factory_id,
            FactoryUpdateFields(
                provided=frozenset(payload.model_fields_set),
                company_id=payload.company_id,
                name=payload.name,
                location=payload.location,
                description=payload.description,
            ),
        )
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return FactoryResponse.model_validate(factory)


@router.delete(
    "/{factory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete a factory",
)
async def delete_factory(
    factory_id: UUID,
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> Response:
    """Soft delete a factory."""
    try:
        await service.delete_factory(factory_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

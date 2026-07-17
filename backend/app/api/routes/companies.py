"""Company routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies.auth import require_roles
from app.dependencies.services import get_manufacturing_service
from app.models.user import User, UserRole
from app.schemas.common import PaginatedResponse, SortOrder
from app.schemas.manufacturing import (
    CompanyCreate,
    CompanyResponse,
    CompanySortField,
    CompanyUpdate,
)
from app.services.exceptions import DuplicateCompanyNameError, ResourceNotFoundError
from app.services.manufacturing import CompanyUpdateFields, ManufacturingService

router = APIRouter(prefix="/companies", tags=["companies"])


def _company_not_found(exc: ResourceNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _company_conflict(exc: DuplicateCompanyNameError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "",
    response_model=PaginatedResponse[CompanyResponse],
    status_code=status.HTTP_200_OK,
    summary="List companies",
)
async def list_companies(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_by: CompanySortField = CompanySortField.CREATED_AT,
    sort_order: SortOrder = SortOrder.ASC,
) -> PaginatedResponse[CompanyResponse]:
    """List active companies with pagination, search, and sorting."""
    page = await service.list_companies(
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[CompanyResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a company",
)
async def create_company(
    payload: CompanyCreate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> CompanyResponse:
    """Create a company."""
    try:
        company = await service.create_company(
            name=payload.name,
            description=payload.description,
        )
    except DuplicateCompanyNameError as exc:
        raise _company_conflict(exc) from exc
    return CompanyResponse.model_validate(company)


@router.get(
    "/{company_id}",
    response_model=CompanyResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a company",
)
async def get_company(
    company_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> CompanyResponse:
    """Return a company by ID."""
    try:
        company = await service.get_company(company_id)
    except ResourceNotFoundError as exc:
        raise _company_not_found(exc) from exc
    return CompanyResponse.model_validate(company)


@router.patch(
    "/{company_id}",
    response_model=CompanyResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a company",
)
async def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> CompanyResponse:
    """Update a company."""
    try:
        company = await service.update_company(
            company_id,
            CompanyUpdateFields(
                provided=frozenset(payload.model_fields_set),
                name=payload.name,
                description=payload.description,
            ),
        )
    except DuplicateCompanyNameError as exc:
        raise _company_conflict(exc) from exc
    except ResourceNotFoundError as exc:
        raise _company_not_found(exc) from exc
    return CompanyResponse.model_validate(company)


@router.delete(
    "/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete a company",
)
async def delete_company(
    company_id: UUID,
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> Response:
    """Soft delete a company."""
    try:
        await service.delete_company(company_id)
    except ResourceNotFoundError as exc:
        raise _company_not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

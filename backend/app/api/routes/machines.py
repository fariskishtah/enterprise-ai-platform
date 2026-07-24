"""Machine routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies.auth import require_roles
from app.dependencies.services import get_audit_service, get_manufacturing_service
from app.models.user import User, UserRole
from app.schemas.common import PaginatedResponse, SortOrder
from app.schemas.manufacturing import (
    MachineCreate,
    MachineResponse,
    MachineSortField,
    MachineUpdate,
)
from app.services.audit import AuditService
from app.services.exceptions import RelatedResourceNotFoundError, ResourceNotFoundError
from app.services.manufacturing import MachineUpdateFields, ManufacturingService

router = APIRouter(prefix="/machines", tags=["machines"])


def _not_found(exc: ResourceNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _related_not_found(exc: RelatedResourceNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@router.get(
    "",
    response_model=PaginatedResponse[MachineResponse],
    status_code=status.HTTP_200_OK,
    summary="List machines",
)
async def list_machines(
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    factory_id: UUID | None = None,
    company_id: UUID | None = None,
    sort_by: MachineSortField = MachineSortField.CREATED_AT,
    sort_order: SortOrder = SortOrder.ASC,
) -> PaginatedResponse[MachineResponse]:
    """List active machines with pagination, filtering, search, and sorting."""
    del company_id  # The authenticated tenant always overrides this legacy filter.
    page = await service.list_machines(
        limit=limit,
        offset=offset,
        search=search,
        factory_id=factory_id,
        company_id=current_user.company_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[MachineResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=MachineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a machine",
)
async def create_machine(
    payload: MachineCreate,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> MachineResponse:
    """Create a machine."""
    try:
        factory = await service.get_factory_for_company(
            payload.factory_id, current_user.company_id
        )
        machine = await service.create_machine(
            factory_id=factory.id,
            name=payload.name,
            serial_number=payload.serial_number,
            manufacturer=payload.manufacturer,
            model=payload.model,
        )
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    except ResourceNotFoundError as exc:
        raise _related_not_found(
            RelatedResourceNotFoundError("Factory does not exist."),
        ) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="machine.created",
        resource_type="machine",
        resource_id=machine.id,
        result="success",
    )
    return MachineResponse.model_validate(machine)


@router.get(
    "/{machine_id}",
    response_model=MachineResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a machine",
)
async def get_machine(
    machine_id: UUID,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
) -> MachineResponse:
    """Return a machine by ID."""
    try:
        machine = await service.get_machine_for_company(
            machine_id, current_user.company_id
        )
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return MachineResponse.model_validate(machine)


@router.patch(
    "/{machine_id}",
    response_model=MachineResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a machine",
)
async def update_machine(
    machine_id: UUID,
    payload: MachineUpdate,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> MachineResponse:
    """Update a machine."""
    try:
        await service.get_machine_for_company(machine_id, current_user.company_id)
        if payload.factory_id is not None:
            await service.get_factory_for_company(
                payload.factory_id, current_user.company_id
            )
        machine = await service.update_machine(
            machine_id,
            MachineUpdateFields(
                provided=frozenset(payload.model_fields_set),
                factory_id=payload.factory_id,
                name=payload.name,
                serial_number=payload.serial_number,
                manufacturer=payload.manufacturer,
                model=payload.model,
            ),
        )
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="machine.updated",
        resource_type="machine",
        resource_id=machine.id,
        result="success",
        metadata={"fields": ",".join(sorted(payload.model_fields_set))},
    )
    return MachineResponse.model_validate(machine)


@router.delete(
    "/{machine_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete a machine",
)
async def delete_machine(
    machine_id: UUID,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[ManufacturingService, Depends(get_manufacturing_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    """Soft delete a machine."""
    try:
        await service.get_machine_for_company(machine_id, current_user.company_id)
        await service.delete_machine(machine_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="machine.deleted",
        resource_type="machine",
        resource_id=machine_id,
        result="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

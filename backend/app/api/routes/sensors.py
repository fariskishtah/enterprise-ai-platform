"""Sensor routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies.auth import require_roles
from app.dependencies.services import get_sensor_service
from app.models.user import User, UserRole
from app.schemas.common import PaginatedResponse, SortOrder
from app.schemas.sensors import (
    SensorCreate,
    SensorResponse,
    SensorSortField,
    SensorUpdate,
)
from app.services.exceptions import (
    DuplicateSensorNameError,
    InvalidSensorRangeError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)
from app.services.sensors import SensorService, SensorUpdateFields

router = APIRouter(prefix="/sensors", tags=["sensors"])
machine_sensor_router = APIRouter(prefix="/machines", tags=["sensors"])


def _not_found(exc: ResourceNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _related_not_found(exc: RelatedResourceNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


def _conflict(exc: DuplicateSensorNameError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _invalid_range(exc: InvalidSensorRangeError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@router.get(
    "",
    response_model=PaginatedResponse[SensorResponse],
    status_code=status.HTTP_200_OK,
    summary="List sensors",
)
async def list_sensors(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorService, Depends(get_sensor_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    machine_id: UUID | None = None,
    sort_by: SensorSortField = SensorSortField.CREATED_AT,
    sort_order: SortOrder = SortOrder.ASC,
) -> PaginatedResponse[SensorResponse]:
    """List active sensors with pagination, filtering, search, and sorting."""
    page = await service.list_sensors(
        limit=limit,
        offset=offset,
        search=search,
        machine_id=machine_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[SensorResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=SensorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sensor",
)
async def create_sensor(
    payload: SensorCreate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[SensorService, Depends(get_sensor_service)],
) -> SensorResponse:
    """Create a sensor."""
    try:
        sensor = await service.create_sensor(
            machine_id=payload.machine_id,
            name=payload.name,
            sensor_type=payload.sensor_type,
            unit=payload.unit,
            sampling_rate=payload.sampling_rate,
            min_value=payload.min_value,
            max_value=payload.max_value,
            description=payload.description,
        )
    except DuplicateSensorNameError as exc:
        raise _conflict(exc) from exc
    except InvalidSensorRangeError as exc:
        raise _invalid_range(exc) from exc
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    return SensorResponse.model_validate(sensor)


@router.get(
    "/{sensor_id}",
    response_model=SensorResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a sensor",
)
async def get_sensor(
    sensor_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorService, Depends(get_sensor_service)],
) -> SensorResponse:
    """Return a sensor by ID."""
    try:
        sensor = await service.get_sensor(sensor_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return SensorResponse.model_validate(sensor)


@router.patch(
    "/{sensor_id}",
    response_model=SensorResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a sensor",
)
async def update_sensor(
    sensor_id: UUID,
    payload: SensorUpdate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[SensorService, Depends(get_sensor_service)],
) -> SensorResponse:
    """Update a sensor."""
    try:
        sensor = await service.update_sensor(
            sensor_id,
            SensorUpdateFields(
                provided=frozenset(payload.model_fields_set),
                machine_id=payload.machine_id,
                name=payload.name,
                sensor_type=payload.sensor_type,
                unit=payload.unit,
                sampling_rate=payload.sampling_rate,
                min_value=payload.min_value,
                max_value=payload.max_value,
                description=payload.description,
            ),
        )
    except DuplicateSensorNameError as exc:
        raise _conflict(exc) from exc
    except InvalidSensorRangeError as exc:
        raise _invalid_range(exc) from exc
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return SensorResponse.model_validate(sensor)


@router.delete(
    "/{sensor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete a sensor",
)
async def delete_sensor(
    sensor_id: UUID,
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[SensorService, Depends(get_sensor_service)],
) -> Response:
    """Soft delete a sensor."""
    try:
        await service.delete_sensor(sensor_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@machine_sensor_router.get(
    "/{machine_id}/sensors",
    response_model=PaginatedResponse[SensorResponse],
    status_code=status.HTTP_200_OK,
    summary="List sensors for a machine",
)
async def list_machine_sensors(
    machine_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorService, Depends(get_sensor_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_by: SensorSortField = SensorSortField.CREATED_AT,
    sort_order: SortOrder = SortOrder.ASC,
) -> PaginatedResponse[SensorResponse]:
    """List active sensors for an active machine."""
    try:
        page = await service.list_machine_sensors(
            machine_id=machine_id,
            limit=limit,
            offset=offset,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return PaginatedResponse(
        items=[SensorResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )

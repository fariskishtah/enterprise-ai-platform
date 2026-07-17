"""Sensor data platform routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.dependencies.auth import require_roles
from app.dependencies.services import (
    get_sensor_data_etl_service,
    get_sensor_data_service,
)
from app.models.sensor_data import ReadingQuality, ReadingSource, UploadJobStatus
from app.models.user import User, UserRole
from app.schemas.common import PaginatedResponse, SortOrder
from app.schemas.sensor_data import (
    SensorReadingCreate,
    SensorReadingResponse,
    SensorReadingSortField,
    UploadJobCreate,
    UploadJobResponse,
    UploadJobSortField,
)
from app.services.exceptions import (
    InvalidSensorDataUploadError,
    InvalidSensorReadingError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)
from app.services.sensor_data import SensorDataService
from app.services.sensor_data_etl import SensorDataEtlService

upload_jobs_router = APIRouter(prefix="/upload-jobs", tags=["upload-jobs"])
sensor_readings_router = APIRouter(
    prefix="/sensor-readings",
    tags=["sensor-readings"],
)
sensor_readings_nested_router = APIRouter(prefix="/sensors", tags=["sensor-readings"])


def _not_found(exc: ResourceNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _related_not_found(exc: RelatedResourceNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


def _invalid_reading(exc: InvalidSensorReadingError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


def _invalid_upload(exc: InvalidSensorDataUploadError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@upload_jobs_router.post(
    "",
    response_model=UploadJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an upload job",
)
async def create_upload_job(
    payload: UploadJobCreate,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[SensorDataService, Depends(get_sensor_data_service)],
) -> UploadJobResponse:
    """Create an upload job."""
    upload_job = await service.create_upload_job(
        filename=payload.filename,
        source=payload.source,
        created_by=current_user.id,
    )
    return UploadJobResponse.model_validate(upload_job)


@upload_jobs_router.post(
    "/{upload_job_id}/csv",
    response_model=UploadJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload sensor readings CSV",
)
async def upload_sensor_readings_csv(
    upload_job_id: UUID,
    file: Annotated[
        UploadFile,
        File(description="CSV file containing sensor readings"),
    ],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[SensorDataEtlService, Depends(get_sensor_data_etl_service)],
) -> UploadJobResponse:
    """Process a CSV file into sensor readings for an upload job."""
    try:
        upload_job = await service.process_csv_upload(
            upload_job_id=upload_job_id,
            file=file.file,
        )
    except InvalidSensorDataUploadError as exc:
        raise _invalid_upload(exc) from exc
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return UploadJobResponse.model_validate(upload_job)


@upload_jobs_router.get(
    "",
    response_model=PaginatedResponse[UploadJobResponse],
    status_code=status.HTTP_200_OK,
    summary="List upload jobs",
)
async def list_upload_jobs(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorDataService, Depends(get_sensor_data_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[UploadJobStatus | None, Query(alias="status")] = None,
    source: ReadingSource | None = None,
    created_by: UUID | None = None,
    sort_by: UploadJobSortField = UploadJobSortField.CREATED_AT,
    sort_order: SortOrder = SortOrder.DESC,
) -> PaginatedResponse[UploadJobResponse]:
    """List upload jobs with pagination and filtering."""
    page = await service.list_upload_jobs(
        limit=limit,
        offset=offset,
        status=status_filter,
        source=source,
        created_by=created_by,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[UploadJobResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@upload_jobs_router.get(
    "/{upload_job_id}",
    response_model=UploadJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an upload job",
)
async def get_upload_job(
    upload_job_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorDataService, Depends(get_sensor_data_service)],
) -> UploadJobResponse:
    """Return an upload job by ID."""
    try:
        upload_job = await service.get_upload_job(upload_job_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return UploadJobResponse.model_validate(upload_job)


@sensor_readings_router.post(
    "",
    response_model=SensorReadingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sensor reading",
)
async def create_sensor_reading(
    payload: SensorReadingCreate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[SensorDataService, Depends(get_sensor_data_service)],
) -> SensorReadingResponse:
    """Create a sensor reading."""
    try:
        reading = await service.create_sensor_reading(
            sensor_id=payload.sensor_id,
            timestamp=payload.timestamp,
            value=float(payload.value),
            quality=payload.quality,
            source=payload.source,
            batch_id=payload.batch_id,
        )
    except InvalidSensorReadingError as exc:
        raise _invalid_reading(exc) from exc
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    return SensorReadingResponse.model_validate(reading)


@sensor_readings_router.get(
    "",
    response_model=PaginatedResponse[SensorReadingResponse],
    status_code=status.HTTP_200_OK,
    summary="List sensor readings",
)
async def list_sensor_readings(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorDataService, Depends(get_sensor_data_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sensor_id: UUID | None = None,
    batch_id: UUID | None = None,
    quality: ReadingQuality | None = None,
    source: ReadingSource | None = None,
    timestamp_from: datetime | None = None,
    timestamp_to: datetime | None = None,
    sort_by: SensorReadingSortField = SensorReadingSortField.TIMESTAMP,
    sort_order: SortOrder = SortOrder.DESC,
) -> PaginatedResponse[SensorReadingResponse]:
    """List sensor readings with pagination and filtering."""
    page = await service.list_sensor_readings(
        limit=limit,
        offset=offset,
        sensor_id=sensor_id,
        batch_id=batch_id,
        quality=quality,
        source=source,
        timestamp_from=timestamp_from,
        timestamp_to=timestamp_to,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[SensorReadingResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@sensor_readings_router.get(
    "/{reading_id}",
    response_model=SensorReadingResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a sensor reading",
)
async def get_sensor_reading(
    reading_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorDataService, Depends(get_sensor_data_service)],
) -> SensorReadingResponse:
    """Return a sensor reading by ID."""
    try:
        reading = await service.get_sensor_reading(reading_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return SensorReadingResponse.model_validate(reading)


@sensor_readings_nested_router.get(
    "/{sensor_id}/readings",
    response_model=PaginatedResponse[SensorReadingResponse],
    status_code=status.HTTP_200_OK,
    summary="List readings for a sensor",
)
async def list_readings_for_sensor(
    sensor_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[SensorDataService, Depends(get_sensor_data_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    quality: ReadingQuality | None = None,
    source: ReadingSource | None = None,
    timestamp_from: datetime | None = None,
    timestamp_to: datetime | None = None,
    sort_by: SensorReadingSortField = SensorReadingSortField.TIMESTAMP,
    sort_order: SortOrder = SortOrder.DESC,
) -> PaginatedResponse[SensorReadingResponse]:
    """List readings for an active sensor."""
    try:
        page = await service.list_readings_for_sensor(
            sensor_id=sensor_id,
            limit=limit,
            offset=offset,
            quality=quality,
            source=source,
            timestamp_from=timestamp_from,
            timestamp_to=timestamp_to,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return PaginatedResponse(
        items=[SensorReadingResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )

"""Authenticated owner-scoped Dataset Registry API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.datasets.domain import (
    DatasetKind,
    DatasetStatus,
    IngestionOptions,
)
from app.datasets.queue import DatasetProcessingQueue
from app.datasets.service import (
    DatasetConflictError,
    DatasetLimits,
    DatasetNotFoundError,
    DatasetQueueError,
    DatasetService,
    DatasetValidationError,
)
from app.dependencies.auth import require_roles
from app.dependencies.database import get_db_session
from app.dependencies.datasets import get_dataset_queue, get_dataset_storage
from app.dependencies.operational import require_training_worker_available
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.models.datasets import Dataset, DatasetVersion, DocumentRecord
from app.models.user import User, UserRole
from app.repositories.datasets import DatasetRepository
from app.schemas.datasets import (
    DatasetArchiveResponse,
    DatasetCreateRequest,
    DatasetListResponse,
    DatasetSchemaResponse,
    DatasetSummaryResponse,
    DatasetVersionListResponse,
    DatasetVersionResponse,
    DocumentListResponse,
    DocumentResponse,
)

router = APIRouter(prefix="/ai/datasets", tags=["AI Datasets"])


def _service(
    session: AsyncSession,
    settings: Settings,
    queue: DatasetProcessingQueue,
) -> DatasetService:
    return DatasetService(
        repository=DatasetRepository(session),
        storage=get_dataset_storage(settings.dataset_storage_root),
        queue=queue,
        limits=DatasetLimits(
            upload_bytes=settings.dataset_upload_max_bytes,
            maximum_rows=settings.dataset_max_rows,
            maximum_columns=settings.dataset_max_columns,
            maximum_cell_characters=settings.dataset_max_cell_characters,
            maximum_document_characters=settings.dataset_max_document_characters,
            stale_after_seconds=settings.dataset_processing_stale_after_seconds,
            maximum_enqueue_attempts=(settings.dataset_processing_max_enqueue_attempts),
        ),
    )


def _scope(user: User) -> UUID | None:
    return None if user.role is UserRole.ADMIN else user.id


def _not_found(exc: DatasetNotFoundError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


def _conflict(exc: DatasetConflictError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


def _dataset_response(value: Dataset) -> DatasetSummaryResponse:
    return DatasetSummaryResponse(
        id=value.id,
        owner_user_id=value.owner_user_id,
        name=value.name,
        description=value.description,
        kind=value.kind,
        status=value.status,
        current_version_id=value.current_version_id,
        state_version=value.state_version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
    )


def _version_response(value: DatasetVersion) -> DatasetVersionResponse:
    return DatasetVersionResponse(
        id=value.id,
        dataset_id=value.dataset_id,
        version_number=value.version_number,
        status=value.status,
        source_type=value.source_type,
        original_filename=value.original_filename,
        media_type=value.media_type,
        size_bytes=value.size_bytes,
        sha256_digest=value.sha256_digest,
        row_count=value.row_count,
        column_count=value.column_count,
        document_count=value.document_count,
        chunk_count=value.chunk_count,
        schema_snapshot=dict(value.schema_snapshot),
        lineage_snapshot=dict(value.lineage_snapshot),
        ingestion_options=dict(value.ingestion_options),
        processing_summary=dict(value.processing_summary),
        created_by_user_id=value.created_by_user_id,
        created_at=value.created_at,
        processing_started_at=value.processing_started_at,
        ready_at=value.ready_at,
        failed_at=value.failed_at,
        archived_at=value.archived_at,
        error_code=value.error_code,
        safe_error_message=value.safe_error_message,
        state_version=value.state_version,
    )


def _document_response(
    value: DocumentRecord, *, include_preview: bool
) -> DocumentResponse:
    preview = None
    if include_preview and value.extracted_text:
        preview = value.extracted_text[:2000]
    return DocumentResponse(
        id=value.id,
        dataset_version_id=value.dataset_version_id,
        document_number=value.document_number,
        title=value.title,
        source_filename=value.source_filename,
        media_type=value.media_type,
        size_bytes=value.size_bytes,
        sha256_digest=value.sha256_digest,
        page_count=value.page_count,
        extracted_character_count=value.extracted_character_count,
        status=value.status,
        text_preview=preview,
        created_at=value.created_at,
        processing_started_at=value.processing_started_at,
        ready_at=value.ready_at,
        failed_at=value.failed_at,
        error_code=value.error_code,
        safe_error_message=value.safe_error_message,
    )


@router.get("", response_model=DatasetListResponse)
async def list_datasets(
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
    kind: DatasetKind | None = None,
    dataset_status: Annotated[DatasetStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> DatasetListResponse:
    page = await _service(session, settings, queue).list_datasets(
        owner_id=_scope(current_user),
        kind=kind,
        status=dataset_status,
        limit=limit,
        offset=offset,
    )
    return DatasetListResponse(
        items=[_dataset_response(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=DatasetSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def create_dataset(
    payload: DatasetCreateRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
) -> DatasetSummaryResponse:
    try:
        value = await _service(session, settings, queue).create_dataset(
            owner_user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            kind=payload.kind,
        )
    except DatasetConflictError as exc:
        raise _conflict(exc) from exc
    return _dataset_response(value)


@router.get("/{dataset_id}", response_model=DatasetSummaryResponse)
async def get_dataset(
    dataset_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
) -> DatasetSummaryResponse:
    try:
        value = await _service(session, settings, queue).get_dataset(
            dataset_id, owner_id=_scope(current_user)
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    return _dataset_response(value)


@router.post(
    "/{dataset_id}/versions",
    response_model=DatasetVersionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(enforce_mutation_rate_limit),
        Depends(require_training_worker_available),
    ],
)
async def create_dataset_version(
    dataset_id: UUID,
    file: Annotated[UploadFile, File()],
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
    target_column: Annotated[str | None, Form(min_length=1, max_length=128)] = None,
    split_column: Annotated[str | None, Form(min_length=1, max_length=128)] = None,
    evaluation_fraction: Annotated[float, Form(ge=0.1, le=0.4)] = 0.2,
) -> DatasetVersionResponse:
    try:
        value = await _service(session, settings, queue).create_version(
            dataset_id=dataset_id,
            owner_id=_scope(current_user),
            created_by_user_id=current_user.id,
            source=file.file,
            filename=file.filename or "",
            media_type=file.content_type or "",
            options=IngestionOptions(
                target_column=target_column,
                split_column=split_column,
                evaluation_fraction=evaluation_fraction,
            ),
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    except DatasetConflictError as exc:
        raise _conflict(exc) from exc
    except DatasetValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except DatasetQueueError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    finally:
        await file.close()
    return _version_response(value)


@router.get("/{dataset_id}/versions", response_model=DatasetVersionListResponse)
async def list_dataset_versions(
    dataset_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> DatasetVersionListResponse:
    try:
        items, total = await _service(session, settings, queue).list_versions(
            dataset_id=dataset_id,
            owner_id=_scope(current_user),
            limit=limit,
            offset=offset,
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    return DatasetVersionListResponse(
        items=[_version_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{dataset_id}/versions/{version_id}", response_model=DatasetVersionResponse
)
async def get_dataset_version(
    dataset_id: UUID,
    version_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
) -> DatasetVersionResponse:
    try:
        value = await _service(session, settings, queue).get_version(
            dataset_id=dataset_id,
            version_id=version_id,
            owner_id=_scope(current_user),
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    return _version_response(value)


@router.get(
    "/{dataset_id}/versions/{version_id}/schema",
    response_model=DatasetSchemaResponse,
)
async def get_dataset_schema(
    dataset_id: UUID,
    version_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
) -> DatasetSchemaResponse:
    try:
        value = await _service(session, settings, queue).get_version(
            dataset_id=dataset_id,
            version_id=version_id,
            owner_id=_scope(current_user),
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    return DatasetSchemaResponse(
        dataset_id=dataset_id,
        version_id=version_id,
        status=value.status,
        schema_snapshot=dict(value.schema_snapshot),
    )


@router.get(
    "/{dataset_id}/versions/{version_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents(
    dataset_id: UUID,
    version_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> DocumentListResponse:
    try:
        items, total = await _service(session, settings, queue).list_documents(
            dataset_id=dataset_id,
            version_id=version_id,
            owner_id=_scope(current_user),
            limit=limit,
            offset=offset,
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    except DatasetConflictError as exc:
        raise _conflict(exc) from exc
    return DocumentListResponse(
        items=[_document_response(item, include_preview=False) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{dataset_id}/versions/{version_id}/documents/{document_id}",
    response_model=DocumentResponse,
)
async def get_document(
    dataset_id: UUID,
    version_id: UUID,
    document_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
) -> DocumentResponse:
    try:
        value = await _service(session, settings, queue).get_document(
            dataset_id=dataset_id,
            version_id=version_id,
            document_id=document_id,
            owner_id=_scope(current_user),
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    return _document_response(value, include_preview=True)


@router.post(
    "/{dataset_id}/archive",
    response_model=DatasetArchiveResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def archive_dataset(
    dataset_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
) -> DatasetArchiveResponse:
    try:
        value = await _service(session, settings, queue).archive_dataset(
            dataset_id, owner_id=_scope(current_user)
        )
    except DatasetNotFoundError as exc:
        raise _not_found(exc) from exc
    except DatasetConflictError as exc:
        raise _conflict(exc) from exc
    assert value.archived_at is not None
    return DatasetArchiveResponse(
        id=value.id,
        status=value.status,
        archived_at=value.archived_at,
    )

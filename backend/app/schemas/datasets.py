"""Bounded public contracts for the versioned Dataset Registry."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.datasets.domain import (
    DatasetKind,
    DatasetSourceType,
    DatasetStatus,
    DatasetVersionStatus,
    DocumentProcessingStatus,
    IngestionOptions,
)
from app.utils.safe_text import ensure_safe_multiline


class DatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$",
    )
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: DatasetKind

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return ensure_safe_multiline(value) if value is not None else None


class DatasetSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    owner_user_id: UUID
    name: str
    description: str | None
    kind: DatasetKind
    status: DatasetStatus
    current_version_id: UUID | None
    state_version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class DatasetListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DatasetSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DatasetVersionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    dataset_id: UUID
    version_number: int = Field(ge=1)
    status: DatasetVersionStatus
    source_type: DatasetSourceType
    original_filename: str | None
    media_type: str
    size_bytes: int = Field(ge=1)
    sha256_digest: str
    row_count: int | None
    column_count: int | None
    document_count: int | None
    chunk_count: int | None
    schema_snapshot: dict[str, object]
    lineage_snapshot: dict[str, object]
    ingestion_options: dict[str, object]
    processing_summary: dict[str, object]
    created_by_user_id: UUID
    created_at: datetime
    processing_started_at: datetime | None
    ready_at: datetime | None
    failed_at: datetime | None
    archived_at: datetime | None
    error_code: str | None
    safe_error_message: str | None
    state_version: int = Field(ge=0)


class DatasetVersionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DatasetVersionResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DatasetSchemaResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: UUID
    version_id: UUID
    status: DatasetVersionStatus
    schema_snapshot: dict[str, object]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    dataset_version_id: UUID
    document_number: int = Field(ge=1)
    title: str
    source_filename: str
    media_type: str
    size_bytes: int = Field(ge=1)
    sha256_digest: str
    page_count: int | None
    extracted_character_count: int = Field(ge=0)
    status: DocumentProcessingStatus
    text_preview: str | None
    created_at: datetime
    processing_started_at: datetime | None
    ready_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    safe_error_message: str | None


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DocumentResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DatasetVersionUploadOptions(IngestionOptions):
    """JSON representation of the multipart ingestion settings."""


class DatasetArchiveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    status: DatasetStatus
    archived_at: datetime

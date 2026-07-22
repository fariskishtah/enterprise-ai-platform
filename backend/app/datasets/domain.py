"""Strict immutable domain contracts for registered datasets."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.utils.safe_text import ensure_safe_multiline

SafeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class DatasetKind(StrEnum):
    TABULAR = "tabular"
    DOCUMENT_COLLECTION = "document_collection"


class DatasetStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    FAILED = "failed"


class DatasetVersionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class DatasetSourceType(StrEnum):
    UPLOAD = "upload"
    GENERATED = "generated"
    IMPORTED_FROM_EXISTING_TRAINING_JOB = "imported_from_existing_training_job"


class DocumentProcessingStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(
        min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$"
    )
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: DatasetKind

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return ensure_safe_multiline(value) if value is not None else None


class TabularColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128)
    data_type: Literal["integer", "float", "string", "boolean"]
    nullable: bool


class TabularSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    columns: tuple[TabularColumn, ...] = Field(min_length=1, max_length=256)
    target_column: str | None = Field(default=None, min_length=1, max_length=128)
    split_column: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_column_references(self) -> TabularSchema:
        names = [column.name for column in self.columns]
        if len(set(names)) != len(names):
            raise ValueError("Dataset columns must be unique.")
        for value in (self.target_column, self.split_column):
            if value is not None and value not in names:
                raise ValueError("Schema column references must exist.")
        if self.target_column is not None and self.target_column == self.split_column:
            raise ValueError("Target and split columns must be different.")
        return self


class DocumentCollectionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    supported_media_types: tuple[Literal["text/plain"], ...] = ("text/plain",)
    maximum_documents: int = Field(default=100, ge=1, le=1000)


class DatasetLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: DatasetSourceType
    source_reference: str | None = Field(default=None, min_length=1, max_length=128)
    parent_version_ids: tuple[str, ...] = Field(default=(), max_length=32)


class StorageObjectMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    size_bytes: int = Field(ge=1, le=50 * 1024 * 1024)
    sha256_digest: Sha256Digest
    media_type: Literal["text/csv", "text/plain"]


class IngestionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_column: str | None = Field(default=None, min_length=1, max_length=128)
    split_column: str | None = Field(default=None, min_length=1, max_length=128)
    evaluation_fraction: float = Field(default=0.2, ge=0.1, le=0.4, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_column_roles(self) -> IngestionOptions:
        if self.target_column is not None and self.target_column == self.split_column:
            raise ValueError("Target and split columns must be different.")
        return self


class ChunkingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_size: int = Field(default=1000, ge=200, le=4000)
    overlap: int = Field(default=100, ge=0, le=1000)
    maximum_chunks: int = Field(default=2000, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_overlap(self) -> ChunkingOptions:
        if self.overlap >= self.chunk_size:
            raise ValueError("Chunk overlap must be smaller than chunk size.")
        return self


class EmbeddingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["local_hashing"] = "local_hashing"
    model: Literal["hashing-v1"] = "hashing-v1"
    dimension: Literal[256] = 256
    batch_size: int = Field(default=32, ge=1, le=128)


class RetentionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retain_days: int | None = Field(default=None, ge=1, le=3650)
    archive_instead_of_delete: Literal[True] = True


class ProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    row_count: int | None = Field(default=None, ge=0, le=10_000)
    column_count: int | None = Field(default=None, ge=0, le=256)
    document_count: int | None = Field(default=None, ge=0, le=1000)
    chunk_count: int | None = Field(default=None, ge=0, le=10_000)
    safe_warnings: tuple[str, ...] = Field(default=(), max_length=20)

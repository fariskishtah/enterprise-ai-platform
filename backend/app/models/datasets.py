"""Authoritative versioned dataset and registered-document persistence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLAlchemyEnum
from sqlalchemy.types import Uuid

from app.datasets.domain import (
    DatasetKind,
    DatasetSourceType,
    DatasetStatus,
    DatasetVersionStatus,
    DocumentProcessingStatus,
)
from app.db.base import Base


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [value.value for value in enum_type]


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "normalized_name", name="uq_datasets_company_name"
        ),
        CheckConstraint("state_version >= 0", name="ck_datasets_state_version"),
        CheckConstraint(
            "kind IN ('tabular','document_collection')", name="ck_datasets_kind"
        ),
        CheckConstraint(
            "status IN ('active','archived','failed')", name="ck_datasets_status"
        ),
        Index("ix_datasets_owner_created", "owner_user_id", "created_at"),
        Index("ix_datasets_company_created", "company_id", "created_at"),
        Index("ix_datasets_kind_status", "kind", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[DatasetKind] = mapped_column(
        SQLAlchemyEnum(
            DatasetKind,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    status: Mapped[DatasetStatus] = mapped_column(
        SQLAlchemyEnum(
            DatasetStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=DatasetStatus.ACTIVE,
        server_default="active",
    )
    current_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "dataset_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_datasets_current_version",
        ),
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        foreign_keys="DatasetVersion.dataset_id",
    )
    current_version: Mapped[DatasetVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "version_number", name="uq_dataset_versions_number"
        ),
        UniqueConstraint(
            "dataset_id", "sha256_digest", name="uq_dataset_versions_digest"
        ),
        CheckConstraint("version_number > 0", name="ck_dataset_versions_number"),
        CheckConstraint("size_bytes > 0", name="ck_dataset_versions_size"),
        CheckConstraint(
            "row_count IS NULL OR row_count >= 0", name="ck_dataset_versions_rows"
        ),
        CheckConstraint(
            "column_count IS NULL OR column_count >= 0",
            name="ck_dataset_versions_columns",
        ),
        CheckConstraint(
            "document_count IS NULL OR document_count >= 0",
            name="ck_dataset_versions_documents",
        ),
        CheckConstraint(
            "chunk_count IS NULL OR chunk_count >= 0",
            name="ck_dataset_versions_chunks",
        ),
        CheckConstraint("state_version >= 0", name="ck_dataset_versions_state_version"),
        CheckConstraint(
            "enqueue_attempt_count BETWEEN 0 AND 100",
            name="ck_dataset_versions_enqueue_attempts",
        ),
        CheckConstraint(
            "status IN ('pending','processing','ready','failed','archived')",
            name="ck_dataset_versions_status",
        ),
        CheckConstraint(
            "source_type IN ('upload','generated',"
            "'imported_from_existing_training_job')",
            name="ck_dataset_versions_source_type",
        ),
        Index("ix_dataset_versions_dataset_created", "dataset_id", "created_at"),
        Index("ix_dataset_versions_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DatasetVersionStatus] = mapped_column(
        SQLAlchemyEnum(
            DatasetVersionStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=DatasetVersionStatus.PENDING,
        server_default="pending",
    )
    source_type: Mapped[DatasetSourceType] = mapped_column(
        SQLAlchemyEnum(
            DatasetSourceType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=64,
        ),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    column_count: Mapped[int | None] = mapped_column(Integer)
    document_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    schema_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    lineage_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    ingestion_options: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    processing_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enqueue_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    dataset: Mapped[Dataset] = relationship(
        back_populates="versions", foreign_keys=[dataset_id]
    )
    documents: Mapped[list[DocumentRecord]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )


class DocumentRecord(Base):
    __tablename__ = "document_records"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "document_number", name="uq_documents_version_number"
        ),
        Index("ix_documents_version_status", "dataset_version_id", "status"),
        CheckConstraint("document_number > 0", name="ck_documents_number"),
        CheckConstraint(
            "status IN ('pending','extracting','chunking','embedding','ready',"
            "'failed','cancelled')",
            name="ck_documents_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_character_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DocumentProcessingStatus] = mapped_column(
        SQLAlchemyEnum(
            DocumentProcessingStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=DocumentProcessingStatus.PENDING,
        server_default="pending",
    )
    extracted_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="documents")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_number", name="uq_document_chunks_number"
        ),
        UniqueConstraint(
            "dataset_version_id", "content_hash", name="uq_document_chunks_hash"
        ),
        Index("ix_document_chunks_version", "dataset_version_id", "chunk_number"),
        Index("ix_document_chunks_embedding", "embedding_status"),
        CheckConstraint("chunk_number >= 0", name="ck_document_chunks_number"),
        CheckConstraint(
            "character_count > 0", name="ck_document_chunks_character_count"
        ),
        CheckConstraint(
            "embedding_status IN ('pending','extracting','chunking','embedding',"
            "'ready','failed','cancelled')",
            name="ck_document_chunks_embedding_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_records.id", ondelete="CASCADE")
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))
    embedding_status: Mapped[DocumentProcessingStatus] = mapped_column(
        SQLAlchemyEnum(
            DocumentProcessingStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=DocumentProcessingStatus.PENDING,
        server_default="pending",
    )
    embedding: Mapped[list[float] | None] = mapped_column(JSON)
    metadata_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[DocumentRecord] = relationship(back_populates="chunks")


class DatasetUsageReference(Base):
    __tablename__ = "dataset_usage_references"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id",
            "usage_type",
            "reference_id",
            name="uq_dataset_usage_reference",
        ),
        Index("ix_dataset_usage_version", "dataset_version_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    usage_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

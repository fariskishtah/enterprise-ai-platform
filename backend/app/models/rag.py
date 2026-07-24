"""Persistent, owner-isolated knowledge-base and grounded-chat state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
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

from app.db.base import Base
from app.rag.domain import (
    GroundedOutcome,
    RAGConversationStatus,
    RAGIndexBuildStatus,
    RAGKnowledgeBaseStatus,
    RAGMessageRole,
    RAGMessageStatus,
)


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]


class RAGKnowledgeBase(Base):
    """Owner-scoped collection of authorized immutable document versions."""

    __tablename__ = "rag_knowledge_bases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','indexing','ready','failed','archived')",
            name="ck_rag_knowledge_bases_status",
        ),
        CheckConstraint(
            "embedding_dimension = 256",
            name="ck_rag_knowledge_bases_embedding_dimension",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_rag_knowledge_bases_state_version"
        ),
        UniqueConstraint(
            "company_id",
            "normalized_name",
            name="uq_rag_knowledge_bases_company_name",
        ),
        Index("ix_rag_knowledge_bases_owner_created", "owner_user_id", "created_at"),
        Index("ix_rag_knowledge_bases_company_created", "company_id", "created_at"),
        Index("ix_rag_knowledge_bases_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RAGKnowledgeBaseStatus] = mapped_column(
        SQLAlchemyEnum(
            RAGKnowledgeBaseStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=RAGKnowledgeBaseStatus.DRAFT,
        server_default="draft",
    )
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    chunking_configuration: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False
    )
    active_index_build_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "rag_index_builds.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_rag_knowledge_bases_active_build",
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
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)

    dataset_versions: Mapped[list[RAGKnowledgeBaseDatasetVersion]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    builds: Mapped[list[RAGIndexBuild]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        foreign_keys="RAGIndexBuild.knowledge_base_id",
    )
    active_index_build: Mapped[RAGIndexBuild | None] = relationship(
        foreign_keys=[active_index_build_id], post_update=True
    )


class RAGKnowledgeBaseDatasetVersion(Base):
    """Authorized immutable dataset version attached to a knowledge base."""

    __tablename__ = "rag_knowledge_base_dataset_versions"
    __table_args__ = (
        Index("ix_rag_kb_dataset_versions_version", "dataset_version_id"),
    )

    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    knowledge_base: Mapped[RAGKnowledgeBase] = relationship(
        back_populates="dataset_versions"
    )


class RAGIndexBuild(Base):
    """One immutable-at-terminal-state knowledge-base indexing attempt."""

    __tablename__ = "rag_index_builds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_rag_index_builds_status",
        ),
        CheckConstraint(
            "indexed_document_count >= 0 AND indexed_chunk_count >= 0 "
            "AND embedding_count >= 0",
            name="ck_rag_index_builds_counts",
        ),
        CheckConstraint("state_version >= 0", name="ck_rag_index_builds_state_version"),
        CheckConstraint(
            "enqueue_attempt_count BETWEEN 0 AND 100",
            name="ck_rag_index_builds_enqueue_attempts",
        ),
        Index("ix_rag_index_builds_kb_created", "knowledge_base_id", "created_at"),
        Index("ix_rag_index_builds_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[RAGIndexBuildStatus] = mapped_column(
        SQLAlchemyEnum(
            RAGIndexBuildStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=RAGIndexBuildStatus.QUEUED,
        server_default="queued",
    )
    indexed_document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    indexed_chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    embedding_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enqueue_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)

    knowledge_base: Mapped[RAGKnowledgeBase] = relationship(
        back_populates="builds", foreign_keys=[knowledge_base_id]
    )
    embeddings: Mapped[list[RAGChunkEmbedding]] = relationship(
        back_populates="index_build", cascade="all, delete-orphan"
    )


class RAGChunkEmbedding(Base):
    """Fixed-width vector for one authorized chunk in one index build."""

    __tablename__ = "rag_chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "embedding_dimension = 256", name="ck_rag_chunk_embeddings_dimension"
        ),
        UniqueConstraint(
            "index_build_id", "chunk_id", name="uq_rag_chunk_embeddings_build_chunk"
        ),
        Index(
            "ix_rag_chunk_embeddings_scope",
            "knowledge_base_id",
            "index_build_id",
        ),
        Index("ix_rag_chunk_embeddings_chunk", "chunk_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    index_build_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_index_builds.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_indexed_chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # PostgreSQL is the production vector store. SQLite keeps a JSON variant so
    # unit tests can exercise the same authorization and lifecycle behavior
    # without pretending to provide production vector-query semantics.
    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(256).with_variant(JSON(), "sqlite"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    index_build: Mapped[RAGIndexBuild] = relationship(back_populates="embeddings")


class RAGIndexedChunk(Base):
    """Deterministic build-specific chunk derived from a registered document."""

    __tablename__ = "rag_indexed_chunks"
    __table_args__ = (
        CheckConstraint("chunk_number >= 0", name="ck_rag_indexed_chunks_number"),
        CheckConstraint(
            "character_count BETWEEN 1 AND 4000",
            name="ck_rag_indexed_chunks_character_count",
        ),
        UniqueConstraint(
            "index_build_id",
            "document_id",
            "chunk_number",
            name="uq_rag_indexed_chunks_build_document_number",
        ),
        Index(
            "ix_rag_indexed_chunks_scope",
            "knowledge_base_id",
            "index_build_id",
        ),
        Index("ix_rag_indexed_chunks_document", "document_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    index_build_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_index_builds.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    chunk_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RAGConversation(Base):
    """Owner-scoped conversation tied to one ready knowledge base."""

    __tablename__ = "rag_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','archived')", name="ck_rag_conversations_status"
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_rag_conversations_state_version"
        ),
        Index("ix_rag_conversations_owner_updated", "owner_user_id", "updated_at"),
        Index("ix_rag_conversations_company_updated", "company_id", "updated_at"),
        Index("ix_rag_conversations_kb", "knowledge_base_id"),
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
    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_knowledge_bases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[RAGConversationStatus] = mapped_column(
        SQLAlchemyEnum(
            RAGConversationStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=RAGConversationStatus.ACTIVE,
        server_default="active",
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

    messages: Mapped[list[RAGMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class RAGMessage(Base):
    """Bounded user or assistant message without hidden chain-of-thought."""

    __tablename__ = "rag_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_rag_messages_role"),
        CheckConstraint(
            "status IN ('queued','retrieving','generating','succeeded',"
            "'failed','cancelled')",
            name="ck_rag_messages_status",
        ),
        CheckConstraint(
            "grounded_outcome IS NULL OR grounded_outcome IN "
            "('grounded','insufficient_evidence')",
            name="ck_rag_messages_grounded_outcome",
        ),
        CheckConstraint(
            "character_count >= 0 AND character_count <= 16000",
            name="ck_rag_messages_character_count",
        ),
        UniqueConstraint(
            "conversation_id", "idempotency_key", name="uq_rag_messages_idempotency"
        ),
        Index("ix_rag_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_rag_messages_reply", "reply_to_message_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    reply_to_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("rag_messages.id", ondelete="RESTRICT")
    )
    role: Mapped[RAGMessageRole] = mapped_column(
        SQLAlchemyEnum(
            RAGMessageRole,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=16,
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RAGMessageStatus] = mapped_column(
        SQLAlchemyEnum(
            RAGMessageStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    grounded_outcome: Mapped[GroundedOutcome | None] = mapped_column(
        SQLAlchemyEnum(
            GroundedOutcome,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        )
    )
    generation_provider: Mapped[str | None] = mapped_column(String(64))
    generation_model: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)

    conversation: Mapped[RAGConversation] = relationship(back_populates="messages")
    citations: Mapped[list[RAGMessageCitation]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class RAGMessageCitation(Base):
    """Immutable registered-document evidence for one assistant message."""

    __tablename__ = "rag_message_citations"
    __table_args__ = (
        CheckConstraint("rank BETWEEN 1 AND 20", name="ck_rag_citations_rank"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_rag_citations_score"),
        UniqueConstraint("message_id", "rank", name="uq_rag_citations_message_rank"),
        UniqueConstraint(
            "message_id", "chunk_id", name="uq_rag_citations_message_chunk"
        ),
        Index("ix_rag_citations_dataset_version", "dataset_version_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    message_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_indexed_chunks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    excerpt: Mapped[str] = mapped_column(String(600), nullable=False)
    document_title: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    message: Mapped[RAGMessage] = relationship(back_populates="citations")

"""Strict public contracts for knowledge-base retrieval and grounded chat."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.rag.domain import (
    GroundedOutcome,
    RAGConversationStatus,
    RAGIndexBuildStatus,
    RAGKnowledgeBaseStatus,
    RAGMessageRole,
    RAGMessageStatus,
)
from app.utils.safe_text import ensure_safe_multiline, ensure_safe_single_line

KnowledgeBaseName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$",
    ),
]
OptionalDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
ConversationTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
MessageContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
IdempotencyKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


class KnowledgeBaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: KnowledgeBaseName
    description: OptionalDescription | None = None
    chunk_size: int = Field(default=1000, ge=200, le=4000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return ensure_safe_multiline(value) if value is not None else None

    @model_validator(mode="after")
    def validate_chunking(self) -> KnowledgeBaseCreateRequest:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("Chunk overlap must be smaller than chunk size.")
        return self


class DatasetVersionAttachmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version_id: UUID


class DatasetVersionAttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    dataset_version_id: UUID
    attached_at: datetime


class KnowledgeBaseSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_base_id: UUID
    name: str
    description: str | None
    status: RAGKnowledgeBaseStatus
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int = Field(gt=0)
    attached_dataset_version_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseDetailResponse(KnowledgeBaseSummaryResponse):
    chunking_configuration: dict[str, object]
    active_index_build_id: UUID | None
    indexed_document_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)
    dataset_versions: list[DatasetVersionAttachmentResponse]
    error_code: str | None
    safe_error_message: str | None
    archived_at: datetime | None


class KnowledgeBasePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[KnowledgeBaseSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class IndexBuildResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index_build_id: UUID
    knowledge_base_id: UUID
    status: RAGIndexBuildStatus
    indexed_document_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)
    embedding_count: int = Field(ge=0)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancelled_at: datetime | None
    error_code: str | None
    safe_error_message: str | None


class IndexBuildPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[IndexBuildResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class RetrievalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: MessageContent
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: FiniteFloat = Field(default=0.05, ge=0, le=1)


class RetrievalResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: UUID
    document_id: UUID
    dataset_version_id: UUID
    rank: int = Field(ge=1, le=20)
    score: float = Field(ge=0, le=1)
    excerpt: str = Field(min_length=1, max_length=500)
    document_title: str = Field(min_length=1, max_length=255)
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=255)


class RetrievalSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_base_id: UUID
    results: list[RetrievalResultResponse]
    insufficient_evidence: bool


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_base_id: UUID
    title: ConversationTitle | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        return ensure_safe_single_line(value) if value is not None else None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: UUID
    knowledge_base_id: UUID
    title: str
    status: RAGConversationStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ConversationPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ConversationResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class MessageSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: MessageContent
    idempotency_key: IdempotencyKey

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return ensure_safe_multiline(value)


class MessageCitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_id: UUID
    chunk_id: UUID
    document_id: UUID
    dataset_version_id: UUID
    rank: int = Field(ge=1, le=20)
    score: float = Field(ge=0, le=1)
    excerpt: str = Field(min_length=1, max_length=500)
    document_title: str = Field(min_length=1, max_length=255)
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=255)


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    conversation_id: UUID
    reply_to_message_id: UUID | None
    role: RAGMessageRole
    content: str = Field(min_length=1, max_length=4000)
    status: RAGMessageStatus
    grounded_outcome: GroundedOutcome | None
    generation_provider: str | None
    generation_model: str | None
    citations: list[MessageCitationResponse]
    created_at: datetime
    completed_at: datetime | None
    error_code: str | None
    safe_error_message: str | None


class MessageExchangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_message: MessageResponse
    assistant_message: MessageResponse


class MessagePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[MessageResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)

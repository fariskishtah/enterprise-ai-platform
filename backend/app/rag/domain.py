"""Immutable domain values for permission-aware retrieval and chat."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class RAGKnowledgeBaseStatus(StrEnum):
    """Knowledge-base lifecycle states."""

    DRAFT = "draft"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class RAGIndexBuildStatus(StrEnum):
    """Index-build lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RAGConversationStatus(StrEnum):
    """Conversation lifecycle states."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class RAGMessageRole(StrEnum):
    """Persisted, user-visible chat roles."""

    USER = "user"
    ASSISTANT = "assistant"


class RAGMessageStatus(StrEnum):
    """Message processing states."""

    QUEUED = "queued"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GroundedOutcome(StrEnum):
    """Whether an answer was supported by registered evidence."""

    GROUNDED = "grounded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """One bounded result returned after an owner-scoped database query."""

    chunk_id: UUID
    document_id: UUID
    dataset_version_id: UUID
    rank: int
    score: float
    excerpt: str
    document_title: str
    page_number: int | None
    section: str | None


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """Safe generated text and its explicit grounding outcome."""

    content: str
    outcome: GroundedOutcome
    cited_ranks: tuple[int, ...]

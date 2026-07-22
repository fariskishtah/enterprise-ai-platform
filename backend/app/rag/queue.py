"""UUID-only queue boundary for durable RAG index builds."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class RAGIndexQueue(Protocol):
    """Enqueue only the authoritative persisted build identifier."""

    def enqueue(self, build_id: UUID) -> str: ...


class DramatiqRAGIndexQueue:
    """Lazy Dramatiq adapter that does not initialize a broker at API import time."""

    def enqueue(self, build_id: UUID) -> str:
        from app.ml.jobs.tasks import build_rag_index

        message = build_rag_index.send(str(build_id))
        return message.message_id


def get_rag_index_queue() -> RAGIndexQueue:
    """Provide an overrideable API-process queue adapter."""
    return DramatiqRAGIndexQueue()

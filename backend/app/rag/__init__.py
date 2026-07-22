"""Secure, local-first retrieval and grounded generation primitives."""

from app.rag.domain import (
    GroundedAnswer,
    GroundedOutcome,
    RAGConversationStatus,
    RAGIndexBuildStatus,
    RAGKnowledgeBaseStatus,
    RAGMessageRole,
    RAGMessageStatus,
    RetrievalResult,
)
from app.rag.embeddings import (
    LOCAL_EMBEDDING_DIMENSION,
    LOCAL_EMBEDDING_MODEL,
    LOCAL_EMBEDDING_PROVIDER,
    DeterministicHashEmbeddingProvider,
    EmbeddingProvider,
)
from app.rag.generation import (
    GroundedGenerationProvider,
    LocalExtractiveGenerationProvider,
)

__all__ = [
    "LOCAL_EMBEDDING_DIMENSION",
    "LOCAL_EMBEDDING_MODEL",
    "LOCAL_EMBEDDING_PROVIDER",
    "DeterministicHashEmbeddingProvider",
    "EmbeddingProvider",
    "GroundedAnswer",
    "GroundedGenerationProvider",
    "GroundedOutcome",
    "LocalExtractiveGenerationProvider",
    "RAGConversationStatus",
    "RAGIndexBuildStatus",
    "RAGKnowledgeBaseStatus",
    "RAGMessageRole",
    "RAGMessageStatus",
    "RetrievalResult",
]

"""Deterministic, dependency-free local text embeddings."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

LOCAL_EMBEDDING_PROVIDER = "local_hashing"
LOCAL_EMBEDDING_MODEL = "hashing-v1"
LOCAL_EMBEDDING_DIMENSION = 256

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_MAX_TEXT_CHARACTERS = 16_000
_MAX_BATCH_SIZE = 64


class EmbeddingProvider(Protocol):
    """Allowlisted local embedding boundary."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


class EmbeddingInputError(ValueError):
    """Raised when bounded provider input is invalid."""


class DeterministicHashEmbeddingProvider:
    """Produce fixed finite lexical vectors without network or model downloads.

    This provider deliberately offers deterministic lexical retrieval for the
    self-hosted baseline. It is not presented as a semantic transformer model.
    """

    @property
    def provider_name(self) -> str:
        return LOCAL_EMBEDDING_PROVIDER

    @property
    def model_name(self) -> str:
        return LOCAL_EMBEDDING_MODEL

    @property
    def dimension(self) -> int:
        return LOCAL_EMBEDDING_DIMENSION

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed a bounded batch into normalized fixed-width vectors."""
        if not texts or len(texts) > _MAX_BATCH_SIZE:
            raise EmbeddingInputError("The embedding batch size is invalid.")
        return tuple(self._embed_one(text) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingInputError("Embedding text must not be empty.")
        if len(text) > _MAX_TEXT_CHARACTERS:
            raise EmbeddingInputError("Embedding text exceeds the safe limit.")

        values = [0.0] * self.dimension
        tokens = tuple(_TOKEN_PATTERN.findall(text.casefold()))
        if not tokens:
            raise EmbeddingInputError("Embedding text contains no indexable terms.")
        for token in tokens:
            digest = hashlib.blake2b(
                token.encode("utf-8"), digest_size=16, person=b"fk-rag-v1"
            ).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] & 1 == 0 else -1.0
            values[bucket] += sign

        norm = math.sqrt(sum(value * value for value in values))
        if not math.isfinite(norm) or norm <= 0:
            raise EmbeddingInputError("Embedding normalization failed.")
        normalized = tuple(value / norm for value in values)
        if len(normalized) != self.dimension or not all(
            math.isfinite(value) for value in normalized
        ):
            raise EmbeddingInputError("Embedding output is invalid.")
        return normalized


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return a finite normalized score for equal-width vectors."""
    if len(left) != LOCAL_EMBEDDING_DIMENSION or len(right) != len(left):
        raise EmbeddingInputError("Embedding dimensions do not match.")
    if not all(math.isfinite(value) for value in (*left, *right)):
        raise EmbeddingInputError("Embedding contains a non-finite value.")
    # Provider outputs are unit-normalized. Negative correlation is not useful
    # evidence, so expose the positive cosine range only.
    cosine = sum(a * b for a, b in zip(left, right, strict=True))
    return max(0.0, min(1.0, cosine))

"""Bounded deterministic character chunking for registered plain text."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


class ChunkingError(ValueError):
    """Raised when text or chunk configuration violates safe bounds."""


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_number: int
    content: str
    content_hash: str


def chunk_text(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    maximum_chunks: int,
) -> tuple[TextChunk, ...]:
    """Split text reproducibly without archive, markup, or token execution."""
    if not 200 <= chunk_size <= 4000:
        raise ChunkingError("Chunk size is outside the safe range.")
    if overlap < 0 or overlap >= chunk_size or overlap > 1000:
        raise ChunkingError("Chunk overlap is outside the safe range.")
    if not 1 <= maximum_chunks <= 2000:
        raise ChunkingError("Maximum chunk count is outside the safe range.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ChunkingError("The registered document contains no extractable text.")
    if len(normalized) > 2_000_000:
        raise ChunkingError("The registered document text exceeds the safe limit.")

    chunks: list[TextChunk] = []
    start = 0
    while start < len(normalized):
        if len(chunks) >= maximum_chunks:
            raise ChunkingError("The registered document exceeds the chunk limit.")
        hard_end = min(start + chunk_size, len(normalized))
        end = hard_end
        if hard_end < len(normalized):
            # Prefer a nearby natural boundary without producing tiny chunks.
            boundary = max(
                normalized.rfind("\n", start + chunk_size // 2, hard_end),
                normalized.rfind(" ", start + chunk_size // 2, hard_end),
            )
            if boundary > start:
                end = boundary
        content = normalized[start:end].strip()
        if content:
            chunks.append(
                TextChunk(
                    chunk_number=len(chunks),
                    content=content,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
        if end >= len(normalized):
            break
        next_start = max(start + 1, end - overlap)
        start = next_start
    if not chunks:
        raise ChunkingError("The registered document contains no indexable text.")
    return tuple(chunks)

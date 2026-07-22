"""Grounded local generation that never executes retrieved instructions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from app.rag.domain import GroundedAnswer, GroundedOutcome, RetrievalResult

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|[\r\n]+")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_MAX_ANSWER_CHARACTERS = 1200
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


class GroundedGenerationProvider(Protocol):
    """Text-generation boundary with no tools, browsing, or external endpoints."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def generate(
        self,
        *,
        question: str,
        evidence: Sequence[RetrievalResult],
        recent_history: Sequence[str],
    ) -> GroundedAnswer: ...


class LocalExtractiveGenerationProvider:
    """Select an evidence sentence without interpreting it as an instruction."""

    @property
    def provider_name(self) -> str:
        return "local_extractive"

    @property
    def model_name(self) -> str:
        return "grounded-extractive-v1"

    def generate(
        self,
        *,
        question: str,
        evidence: Sequence[RetrievalResult],
        recent_history: Sequence[str],
    ) -> GroundedAnswer:
        """Return cited evidence or an explicit insufficient-evidence response.

        Recent history is accepted to keep the provider contract future-proof but
        is deliberately not interpreted by this deterministic local provider.
        Retrieved document text is treated only as quoted data; it cannot trigger
        tools, network calls, or changes to system behavior.
        """
        _ = recent_history
        if not evidence:
            return GroundedAnswer(
                content=(
                    "The registered documents do not contain enough evidence to "
                    "answer this question."
                ),
                outcome=GroundedOutcome.INSUFFICIENT_EVIDENCE,
                cited_ranks=(),
            )

        question_terms = _significant_terms(question)
        if not question_terms:
            return GroundedAnswer(
                content=(
                    "The registered documents do not contain enough evidence to "
                    "answer this question."
                ),
                outcome=GroundedOutcome.INSUFFICIENT_EVIDENCE,
                cited_ranks=(),
            )

        min_required_overlap = 1 if len(question_terms) == 1 else 2
        min_required_coverage = 0.5

        candidates: list[tuple[float, int, int, str]] = []
        for result in evidence:
            for sentence in _SENTENCE_BOUNDARY.split(result.excerpt):
                normalized = " ".join(sentence.split()).strip()
                if not normalized:
                    continue
                terms = _significant_terms(normalized)
                overlap_terms = question_terms & terms
                overlap_count = len(overlap_terms)
                coverage = overlap_count / len(question_terms)

                if (
                    overlap_count < min_required_overlap
                    or coverage < min_required_coverage
                ):
                    continue

                candidates.append((coverage, overlap_count, -result.rank, normalized))

        if not candidates:
            return GroundedAnswer(
                content=(
                    "The registered documents do not contain enough evidence to "
                    "answer this question."
                ),
                outcome=GroundedOutcome.INSUFFICIENT_EVIDENCE,
                cited_ranks=(),
            )

        _coverage, _overlap, negative_rank, sentence = max(candidates)
        rank = -negative_rank
        bounded_sentence = sentence[:_MAX_ANSWER_CHARACTERS].rstrip()
        return GroundedAnswer(
            content=f"According to registered source [{rank}], {bounded_sentence}",
            outcome=GroundedOutcome.GROUNDED,
            cited_ranks=(rank,),
        )


def _significant_terms(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(value.casefold())
        if token not in _STOP_WORDS
    }

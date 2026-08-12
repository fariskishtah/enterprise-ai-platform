"""Grounded local generation that never executes retrieved instructions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from app.rag.domain import GroundedAnswer, GroundedOutcome, RetrievalResult

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|[\r\n]+")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_MAX_ANSWER_CHARACTERS = 1200
LOCAL_EXTRACTIVE_PROVIDER_NAME = "local_extractive"
LOCAL_EXTRACTIVE_MODEL_NAME = "grounded-extractive-v2"
_UNSAFE_EVIDENCE_PATTERNS = (
    "ignore previous instructions",
    "ignore all instructions",
    "override system instructions",
    "system instructions",
    "reveal the system prompt",
    "reveal internal instructions",
    "browse the internet",
    "do not cite",
)
_SENSITIVE_REQUEST_PATTERNS = (
    "system prompt",
    "internal prompt",
    "internal instructions",
    "api key",
    "access token",
    "password",
    "credential",
    "secret key",
)
_CONTROL_REQUEST_PATTERNS = (
    "ignore previous instructions",
    "ignore all instructions",
    "ignore grounding",
    "override system instructions",
)
_FACT_VALUE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:days?|hours?|minutes?|°?c|bar|psi|rpm|units?(?:/shift)?)\b",
    re.IGNORECASE,
)
_TERM_ALIASES: dict[str, frozenset[str]] = {
    "serviced": frozenset({"maintenance"}),
    "servicing": frozenset({"maintenance"}),
    "maintained": frozenset({"maintenance"}),
    "often": frozenset({"interval", "frequency", "schedule"}),
    "frequency": frozenset({"interval", "schedule"}),
    "schedule": frozenset({"interval", "frequency"}),
    "hot": frozenset({"temperature"}),
    "heat": frozenset({"temperature"}),
    "output": frozenset({"production", "target"}),
    "quota": frozenset({"production", "target"}),
    "stop": frozenset({"shutdown", "emergency"}),
    "shut": frozenset({"shutdown"}),
}
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
        return LOCAL_EXTRACTIVE_PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return LOCAL_EXTRACTIVE_MODEL_NAME

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
        if _is_sensitive_extraction_request(question):
            return GroundedAnswer(
                content=(
                    "I cannot provide system prompts, credentials, secrets, or "
                    "other internal control information."
                ),
                outcome=GroundedOutcome.INSUFFICIENT_EVIDENCE,
                cited_ranks=(),
            )
        if not evidence:
            return _insufficient_answer()

        question_terms = _significant_terms(_strip_control_phrases(question))
        if not question_terms:
            return _insufficient_answer()

        min_required_overlap = 1 if len(question_terms) == 1 else 2
        min_required_coverage = 0.4 if " and " in question.casefold() else 0.5

        candidates: list[tuple[float, int, float, int, str, frozenset[str]]] = []
        for result in evidence:
            for sentence in _SENTENCE_BOUNDARY.split(result.excerpt):
                normalized = " ".join(sentence.split()).strip()
                if not normalized or _is_unsafe_evidence_sentence(normalized):
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

                candidates.append(
                    (
                        coverage,
                        overlap_count,
                        result.score,
                        result.rank,
                        normalized,
                        frozenset(overlap_terms),
                    )
                )

        if not candidates:
            return _insufficient_answer()

        candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        best = candidates[0]
        conflicting = next(
            (
                candidate
                for candidate in candidates[1:]
                if candidate[3] != best[3]
                and _term_overlap_ratio(best[5], candidate[5]) >= 0.75
                and _facts_conflict(best[4], candidate[4])
            ),
            None,
        )
        if conflicting is not None:
            first_sentence = best[4][: _MAX_ANSWER_CHARACTERS // 2].rstrip()
            second_sentence = conflicting[4][: _MAX_ANSWER_CHARACTERS // 2].rstrip()
            return GroundedAnswer(
                content=(
                    f"Registered sources conflict: [{best[3]}] {first_sentence} "
                    f"[{conflicting[3]}] {second_sentence} Please confirm which "
                    "source is authoritative before acting."
                ),
                outcome=GroundedOutcome.GROUNDED,
                cited_ranks=(best[3], conflicting[3]),
            )

        selected = [best]
        covered_terms = set(best[5])
        if " and " in question.casefold():
            complementary = next(
                (
                    candidate
                    for candidate in candidates[1:]
                    if candidate[3] != best[3]
                    and bool(set(candidate[5]) - covered_terms)
                ),
                None,
            )
            if complementary is not None:
                selected.append(complementary)

        answer_parts = [f"[{candidate[3]}] {candidate[4]}" for candidate in selected]
        bounded_answer = " ".join(answer_parts)[:_MAX_ANSWER_CHARACTERS].rstrip()
        return GroundedAnswer(
            content=f"According to registered sources, {bounded_answer}",
            outcome=GroundedOutcome.GROUNDED,
            cited_ranks=tuple(candidate[3] for candidate in selected),
        )


def _significant_terms(value: str) -> set[str]:
    terms = {
        token
        for token in _TOKEN_PATTERN.findall(value.casefold())
        if token not in _STOP_WORDS
    }
    expanded = set(terms)
    for term in terms:
        expanded.update(_TERM_ALIASES.get(term, ()))
    return expanded


def expand_retrieval_query(value: str) -> str:
    """Append bounded domain aliases to improve deterministic lexical recall."""
    terms = _significant_terms(_strip_control_phrases(value))
    original_terms = set(_TOKEN_PATTERN.findall(value.casefold()))
    additions = sorted(terms - original_terms)
    return value if not additions else f"{value} {' '.join(additions)}"


def _insufficient_answer() -> GroundedAnswer:
    return GroundedAnswer(
        content=(
            "The registered documents do not contain enough evidence to answer "
            "this question."
        ),
        outcome=GroundedOutcome.INSUFFICIENT_EVIDENCE,
        cited_ranks=(),
    )


def _strip_control_phrases(value: str) -> str:
    sanitized = value
    for phrase in _CONTROL_REQUEST_PATTERNS:
        sanitized = re.sub(re.escape(phrase), " ", sanitized, flags=re.IGNORECASE)
    return " ".join(sanitized.split())


def _is_sensitive_extraction_request(value: str) -> bool:
    normalized = value.casefold()
    extraction_verbs = (
        "show",
        "reveal",
        "print",
        "list",
        "extract",
        "repeat",
        "give",
        "what",
        "which",
    )
    return any(term in normalized for term in _SENSITIVE_REQUEST_PATTERNS) and any(
        verb in normalized for verb in extraction_verbs
    )


def _is_unsafe_evidence_sentence(value: str) -> bool:
    normalized = value.casefold()
    return any(pattern in normalized for pattern in _UNSAFE_EVIDENCE_PATTERNS)


def _facts_conflict(left: str, right: str) -> bool:
    left_values = {match.casefold() for match in _FACT_VALUE_PATTERN.findall(left)}
    right_values = {match.casefold() for match in _FACT_VALUE_PATTERN.findall(right)}
    return bool(left_values and right_values and left_values.isdisjoint(right_values))


def _term_overlap_ratio(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)

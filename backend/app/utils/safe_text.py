"""Small shared validators for database-safe user text."""

from __future__ import annotations

import unicodedata


def ensure_safe_single_line(value: str) -> str:
    """Reject control and surrogate code points from labels and filenames."""
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
        raise ValueError("Text contains unsupported control characters.")
    return value


def ensure_safe_multiline(value: str) -> str:
    """Allow ordinary whitespace while rejecting unsafe database code points."""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if any(
        unicodedata.category(character) in {"Cc", "Cs"}
        and character not in {"\t", "\n"}
        for character in normalized
    ):
        raise ValueError("Text contains unsupported control characters.")
    return normalized

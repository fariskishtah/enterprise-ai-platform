"""Unicode-safe dataset display-name validation and uniqueness normalization."""

from __future__ import annotations

import unicodedata

from app.utils.safe_text import ensure_safe_single_line


def validate_dataset_display_name(value: str) -> str:
    """Allow ordinary Unicode names while rejecting unsafe structural characters."""
    normalized_spacing = " ".join(value.split())
    ensure_safe_single_line(normalized_spacing)
    if len(normalized_spacing) < 3 or len(normalized_spacing) > 128:
        raise ValueError("Dataset names must contain between 3 and 128 characters.")
    if not normalized_spacing[0].isalnum():
        raise ValueError("Dataset names must begin with a letter or number.")
    forbidden = {"/", "\\", "<", ">", "\u2028", "\u2029"}
    if any(character in forbidden for character in normalized_spacing):
        raise ValueError(
            "Dataset names cannot contain path separators or angle brackets."
        )
    if any(
        not (
            character == " "
            or character.isalnum()
            or unicodedata.category(character)[0] in {"L", "M", "N", "P"}
        )
        for character in normalized_spacing
    ):
        raise ValueError(
            "Dataset names may use letters, numbers, spaces, and normal punctuation."
        )
    return normalized_spacing


def normalize_dataset_name(value: str) -> str:
    """Return a stable internal comparison key without altering the display value."""
    return unicodedata.normalize(
        "NFKC", validate_dataset_display_name(value)
    ).casefold()

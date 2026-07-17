"""Security utility functions."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hash_token(token: str) -> str:
    """Return a stable SHA-256 digest for a bearer token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    """Normalize email addresses for unique comparisons."""
    return email.strip().lower()

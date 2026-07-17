"""JSON value validation helpers."""

from __future__ import annotations

import json


def ensure_json_serializable(value: object, *, field_name: str) -> None:
    """Raise ValueError when a value cannot be represented as strict JSON."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        msg = f"{field_name} must be JSON serializable."
        raise ValueError(msg) from exc

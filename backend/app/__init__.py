"""AI Manufacturing Platform backend package."""

from __future__ import annotations

import sys

_SUPPORTED_PYTHON = (3, 12)

if sys.version_info[:2] != _SUPPORTED_PYTHON:
    detected = ".".join(str(part) for part in sys.version_info[:2])
    raise RuntimeError(
        "The AI Manufacturing Platform backend requires Python 3.12; "
        f"detected Python {detected}."
    )

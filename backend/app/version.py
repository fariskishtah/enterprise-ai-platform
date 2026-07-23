"""Canonical application version resolution."""

from functools import lru_cache
from pathlib import Path

_VERSION_FILENAME = "VERSION"


@lru_cache
def get_application_version() -> str:
    """Read the repository-owned canonical version file.

    The Docker image copies ``VERSION`` to ``/app/VERSION``. Source checkouts find
    the same file by walking up from this module. Package metadata and frontend
    metadata are synchronized projections verified by the release validation
    script.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _VERSION_FILENAME
        if candidate.is_file():
            value = candidate.read_text(encoding="utf-8").strip()
            if value:
                return value
    raise RuntimeError("Canonical VERSION file was not found or is empty.")

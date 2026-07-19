"""Public local model-artifact contracts."""

from app.ml.artifacts.base import BaseArtifactManager
from app.ml.artifacts.exceptions import (
    ArtifactAlreadyExistsError,
    ArtifactManagerError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactTypeMismatchError,
)
from app.ml.artifacts.local import LocalArtifactManager
from app.ml.artifacts.models import (
    ArtifactDestination,
    ArtifactFormat,
    ArtifactInfo,
)

__all__ = [
    "ArtifactAlreadyExistsError",
    "ArtifactDestination",
    "ArtifactFormat",
    "ArtifactInfo",
    "ArtifactManagerError",
    "ArtifactNotFoundError",
    "ArtifactPathError",
    "ArtifactTypeMismatchError",
    "BaseArtifactManager",
    "LocalArtifactManager",
]

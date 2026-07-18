"""Root-scoped Joblib persistence for local fitted models."""

import re
from pathlib import Path

import joblib  # type: ignore[import-untyped]

from app.ml.artifacts.base import BaseArtifactManager
from app.ml.artifacts.exceptions import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactTypeMismatchError,
)
from app.ml.artifacts.models import (
    ArtifactDestination,
    ArtifactFormat,
    ArtifactInfo,
)

_SAFE_COMPONENT = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class LocalArtifactManager(BaseArtifactManager):
    """Persist models beneath one explicitly supplied local root."""

    def __init__(self, root_directory: Path) -> None:
        self._root_directory = root_directory.resolve()
        self._root_directory.mkdir(parents=True, exist_ok=True)

    @property
    def root_directory(self) -> Path:
        """Return the resolved instance-specific artifact root."""
        return self._root_directory

    def save[
        ModelT
    ](self, model: ModelT, destination: ArtifactDestination,) -> ArtifactInfo:
        """Serialize a model without overwriting an existing run artifact."""
        artifact_path = self._destination_path(destination)
        if artifact_path.exists():
            msg = f"Artifact already exists at '{artifact_path}'."
            raise ArtifactAlreadyExistsError(msg)

        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if artifact_path.exists():
            msg = f"Artifact already exists at '{artifact_path}'."
            raise ArtifactAlreadyExistsError(msg)
        # TODO: Persist through a same-directory temporary file and atomically
        # promote it before production job execution is enabled.
        joblib.dump(model, artifact_path)
        return ArtifactInfo(
            path=artifact_path,
            size_bytes=artifact_path.stat().st_size,
            format=ArtifactFormat.JOBLIB,
        )

    def load[
        ModelT
    ](self, artifact: ArtifactInfo, expected_type: type[ModelT],) -> ModelT:
        """Load an in-root Joblib artifact and validate its runtime type."""
        artifact_path = self._in_root_path(artifact.path)
        if not artifact_path.is_file():
            msg = f"Artifact does not exist at '{artifact_path}'."
            raise ArtifactNotFoundError(msg)

        loaded: object = joblib.load(artifact_path)
        if not isinstance(loaded, expected_type):
            msg = (
                f"Artifact at '{artifact_path}' contains '{type(loaded).__name__}', "
                f"expected '{expected_type.__name__}'."
            )
            raise ArtifactTypeMismatchError(msg)
        return loaded

    def _destination_path(self, destination: ArtifactDestination) -> Path:
        components = (
            destination.key.algorithm.value,
            destination.key.task_type.value,
        )
        for component in components:
            if _SAFE_COMPONENT.fullmatch(component) is None:
                msg = f"Unsafe artifact path component '{component}'."
                raise ArtifactPathError(msg)

        candidate = self._root_directory.joinpath(
            *components,
            str(destination.run_id),
            "model.joblib",
        )
        return self._in_root_path(candidate)

    def _in_root_path(self, path: Path) -> Path:
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(self._root_directory)
        except ValueError as exc:
            msg = (
                f"Artifact path '{resolved_path}' is outside root "
                f"'{self._root_directory}'."
            )
            raise ArtifactPathError(msg) from exc
        return resolved_path

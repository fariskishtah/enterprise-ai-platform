"""Generic persistence port for fitted in-memory models."""

from abc import ABC, abstractmethod

from app.ml.artifacts.models import ArtifactDestination, ArtifactInfo


class BaseArtifactManager(ABC):
    """Save and load models without exposing serialization internals."""

    @abstractmethod
    def save[
        ModelT
    ](self, model: ModelT, destination: ArtifactDestination,) -> ArtifactInfo:
        """Persist a model at a typed deterministic destination."""

    @abstractmethod
    def load[
        ModelT
    ](self, artifact: ArtifactInfo, expected_type: type[ModelT],) -> ModelT:
        """Load and runtime-check a model before returning its static type."""

"""Minimal fitted-model registry port."""

from abc import ABC, abstractmethod

from app.ml.registry.models import ModelRegistrationRequest, RegisteredModelVersion


class BaseModelRegistry(ABC):
    """Register and resolve fitted model versions without SDK leakage."""

    @abstractmethod
    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        """Register one tracked model artifact."""

    @abstractmethod
    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        """Resolve an exact version or alias to immutable platform metadata."""

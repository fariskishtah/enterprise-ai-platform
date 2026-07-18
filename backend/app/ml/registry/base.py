"""Minimal fitted-model registry port."""

from abc import ABC, abstractmethod

from app.ml.registry.models import (
    ModelRegistrationRequest,
    RegisteredModelAlias,
    RegisteredModelVersion,
)


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

    def assign_alias(
        self,
        registered_model_name: str,
        alias: str,
        version: str,
    ) -> RegisteredModelVersion:
        """Assign and verify an alias when supported by the adapter."""
        raise NotImplementedError

    def list_aliases(
        self,
        registered_model_name: str,
    ) -> tuple[RegisteredModelAlias, ...]:
        """List platform-owned aliases when supported by the adapter."""
        raise NotImplementedError

"""Registered-model loading port and MLflow artifact implementation."""

from abc import ABC, abstractmethod
from pathlib import Path

import joblib  # type: ignore[import-untyped]
from mlflow.artifacts import download_artifacts

from app.ml.registry import RegisteredModelVersion
from app.ml.services.exceptions import (
    RegisteredModelLoadError,
    RegisteredModelTypeMismatchError,
)


class BaseRegisteredModelLoader(ABC):
    """Load a registered model while preserving its checked concrete type."""

    @abstractmethod
    def load[
        ModelT
    ](
        self,
        model_version: RegisteredModelVersion,
        expected_type: type[ModelT],
    ) -> ModelT:
        """Load and runtime-check one resolved registered model version."""


class MLflowRegisteredModelLoader(BaseRegisteredModelLoader):
    """Download an MLflow-registered Joblib artifact and check its model type."""

    def __init__(self, *, tracking_uri: str) -> None:
        if not tracking_uri.strip():
            raise ValueError("tracking_uri must be non-empty.")
        self._tracking_uri = tracking_uri

    def load[
        ModelT
    ](
        self,
        model_version: RegisteredModelVersion,
        expected_type: type[ModelT],
    ) -> ModelT:
        """Download through MLflow and deserialize only inside this boundary."""
        try:
            downloaded_path = Path(
                download_artifacts(
                    artifact_uri=model_version.source_uri,
                    tracking_uri=self._tracking_uri,
                ),
            )
            loaded: object = joblib.load(downloaded_path)
        except Exception as exc:
            raise RegisteredModelLoadError(
                "The registered model artifact could not be loaded.",
            ) from exc
        if not isinstance(loaded, expected_type):
            raise RegisteredModelTypeMismatchError(
                f"Registered model contains '{type(loaded).__name__}', expected "
                f"'{expected_type.__name__}'.",
            )
        return loaded

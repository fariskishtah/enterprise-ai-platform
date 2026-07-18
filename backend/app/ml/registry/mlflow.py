"""MLflow fitted-model registry adapter."""

from mlflow.entities.model_registry import ModelVersion
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.registry.base import BaseModelRegistry
from app.ml.registry.exceptions import (
    ModelRegistrationError,
    ModelRegistryError,
    RegisteredModelVersionNotFoundError,
    RegistryMetadataError,
)
from app.ml.registry.models import (
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionStatus,
)
from app.ml.registry.naming import (
    validate_registered_model_name,
    validate_version_or_alias,
)

_RESOURCE_DOES_NOT_EXIST = "RESOURCE_DOES_NOT_EXIST"
_RESOURCE_ALREADY_EXISTS = "RESOURCE_ALREADY_EXISTS"


class MLflowModelRegistry(BaseModelRegistry):
    """Register and resolve fitted model artifacts through MLflow."""

    def __init__(self, *, tracking_uri: str) -> None:
        if not tracking_uri.strip():
            raise ValueError("tracking_uri must be non-empty.")
        self._client = MlflowClient(tracking_uri=tracking_uri)

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        """Register a completed run artifact without promotion or deletion."""
        protected_tags = {
            "algorithm": request.key.algorithm.value,
            "task_type": request.key.task_type.value,
            "platform_component": "ai_core",
        }
        tags = {**request.tags, **protected_tags}
        try:
            self._ensure_registered_model(
                request.registered_model_name,
                tags=protected_tags,
            )
            model_version = self._client.create_model_version(
                name=request.registered_model_name,
                source=request.artifact_uri,
                run_id=request.source_run_id,
                tags=tags,
                description=request.description,
            )
        except ModelRegistryError:
            raise
        except Exception as exc:
            raise ModelRegistrationError(
                "MLflow could not register the completed AI Core model.",
            ) from exc
        return self._to_platform_version(model_version)

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        """Resolve an exact version or alias without changing model state."""
        name = validate_registered_model_name(registered_model_name)
        reference = validate_version_or_alias(version_or_alias)
        try:
            if reference.isdigit():
                model_version = self._client.get_model_version(name, reference)
            else:
                model_version = self._client.get_model_version_by_alias(
                    name,
                    reference,
                )
        except MlflowException as exc:
            if exc.error_code == _RESOURCE_DOES_NOT_EXIST:
                raise RegisteredModelVersionNotFoundError(
                    "The requested registered model version or alias was not found.",
                ) from exc
            raise ModelRegistryError(
                "MLflow could not resolve the requested model version.",
            ) from exc
        return self._to_platform_version(model_version)

    def _ensure_registered_model(
        self,
        name: str,
        *,
        tags: dict[str, str],
    ) -> None:
        try:
            self._client.get_registered_model(name)
            return
        except MlflowException as exc:
            if exc.error_code != _RESOURCE_DOES_NOT_EXIST:
                raise ModelRegistryError(
                    "MLflow could not inspect the registered model.",
                ) from exc

        try:
            self._client.create_registered_model(name=name, tags=tags)
        except MlflowException as exc:
            if exc.error_code != _RESOURCE_ALREADY_EXISTS:
                raise ModelRegistrationError(
                    "MLflow could not create the registered model.",
                ) from exc

    def _to_platform_version(
        self,
        model_version: ModelVersion,
    ) -> RegisteredModelVersion:
        name = str(model_version.name)
        version = str(model_version.version)
        run_id_value = model_version.run_id
        source_uri = str(model_version.source)
        status_value = str(model_version.status)
        raw_tags = model_version.tags
        raw_aliases = model_version.aliases

        if not isinstance(run_id_value, str):
            raise RegistryMetadataError(
                "The registered model version is not linked to a source run.",
            )
        if not isinstance(raw_tags, dict):
            raise RegistryMetadataError(
                "The registered model version has invalid tag metadata.",
            )
        if not isinstance(raw_aliases, list) or not all(
            isinstance(alias, str) for alias in raw_aliases
        ):
            raise RegistryMetadataError(
                "The registered model version has invalid alias metadata.",
            )

        try:
            key = TrainerKey(
                algorithm=AlgorithmType(raw_tags["algorithm"]),
                task_type=TaskType(raw_tags["task_type"]),
            )
            status = RegisteredModelVersionStatus(status_value)
        except (KeyError, ValueError) as exc:
            raise RegistryMetadataError(
                "The registered model version lacks valid AI Core metadata.",
            ) from exc
        return RegisteredModelVersion(
            registered_model_name=name,
            version=version,
            run_id=run_id_value,
            source_uri=source_uri,
            key=key,
            status=status,
            aliases=tuple(sorted(raw_aliases)),
        )

"""Generic typed prediction from resolved registered model versions."""

from app.ml.registry import BaseModelRegistry
from app.ml.services.exceptions import PredictionTrainerKeyMismatchError
from app.ml.services.loader import BaseRegisteredModelLoader
from app.ml.services.types import (
    RegisteredPredictionObserver,
    RegisteredPredictionPlan,
    RegisteredPredictionRequest,
    RegisteredPredictionResult,
)
from app.observability.tracing import traced_operation


class PredictionService:
    """Resolve, load, validate, and predict without retraining models."""

    def __init__(
        self,
        *,
        model_registry: BaseModelRegistry,
        model_loader: BaseRegisteredModelLoader,
    ) -> None:
        self._model_registry = model_registry
        self._model_loader = model_loader

    @traced_operation(
        "prediction.execution",
        attributes={"algorithm": "random_forest", "trigger": "api"},
    )
    def predict[
        ModelT, FeaturesT, PredictionsT
    ](
        self,
        plan: RegisteredPredictionPlan[ModelT, FeaturesT, PredictionsT],
        request: RegisteredPredictionRequest[FeaturesT],
        *,
        observer: RegisteredPredictionObserver | None = None,
    ) -> RegisteredPredictionResult[PredictionsT]:
        """Execute prediction through one explicit typed composition plan."""
        model_version = self._model_registry.resolve(
            request.registered_model_name,
            request.version_or_alias,
        )
        if observer is not None:
            observer.model_resolved(model_version)
        if model_version.key != plan.key:
            raise PredictionTrainerKeyMismatchError(
                f"Registered model uses '{model_version.key}', expected '{plan.key}'.",
            )
        model = self._model_loader.load(model_version, plan.expected_model_type)
        features = plan.validate_features(request.features)
        predictions = plan.predict(model, features)
        return RegisteredPredictionResult(
            model_version=model_version,
            predictions=predictions,
            loaded_model=model,
        )

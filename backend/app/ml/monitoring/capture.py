"""Resilient prediction-event capture around the pure prediction service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from app.ml.monitoring.models import (
    ModelReferenceProfile,
    PredictionEvent,
    PredictionEventStatus,
)
from app.ml.monitoring.profiles import (
    feature_request_profiles,
    prediction_request_profile,
)
from app.ml.registry import (
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
    RegistryMetadataError,
)
from app.ml.services import (
    PredictionService,
    PredictionTrainerKeyMismatchError,
    RegisteredModelLoadError,
    RegisteredModelTypeMismatchError,
    RegisteredPredictionPlan,
    RegisteredPredictionRequest,
    RegisteredPredictionResult,
)
from app.ml.trainers.random_forest import TrainerDataValidationError
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    FeatureArray,
    RegressionPredictionArray,
)
from app.utils.security import utc_now

logger = logging.getLogger(__name__)


class PredictionEventStore(Protocol):
    """Minimal persistence port required by prediction capture."""

    async def create_event(self, event: PredictionEvent) -> PredictionEvent:
        """Stage one event for persistence."""

    async def get_reference_profile(
        self,
        registered_model_name: str,
        model_version: str,
    ) -> ModelReferenceProfile | None:
        """Return the exact-version profile when one exists."""

    async def commit(self) -> None:
        """Commit the active monitoring transaction."""

    async def rollback(self) -> None:
        """Roll back the active monitoring transaction."""


@dataclass(frozen=True, slots=True)
class PredictionCaptureContext:
    """Authenticated request metadata safe for an event record."""

    requested_by_user_id: UUID
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class PredictionCaptureHealthSnapshot:
    """Instance-local capture failures accumulated since process start."""

    instance_capture_failures_since_start: int


class PredictionCaptureHealth:
    """Thread-safe instance-local signal that resets with the API process."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._persistence_failure_count = 0

    def record_persistence_failure(self) -> None:
        """Increment after an event read/write transaction fails."""
        with self._lock:
            self._persistence_failure_count += 1

    def snapshot(self) -> PredictionCaptureHealthSnapshot:
        """Return the stable current process count."""
        with self._lock:
            return PredictionCaptureHealthSnapshot(
                instance_capture_failures_since_start=(self._persistence_failure_count),
            )


class _ResolutionObserver:
    """Request-local holder for safe resolution metadata on later failures."""

    def __init__(self) -> None:
        self.version: RegisteredModelVersion | None = None

    def model_resolved(self, version: RegisteredModelVersion) -> None:
        self.version = version


class MonitoredPredictionService:
    """Execute prediction once, then best-effort persist privacy-safe telemetry."""

    def __init__(
        self,
        *,
        prediction_service: PredictionService,
        event_store: PredictionEventStore,
        capture_health: PredictionCaptureHealth,
    ) -> None:
        self._prediction_service = prediction_service
        self._event_store = event_store
        self._capture_health = capture_health

    async def predict[
        ModelT,
        PredictionsT: (RegressionPredictionArray | ClassificationPredictionArray),
    ](
        self,
        plan: RegisteredPredictionPlan[ModelT, FeatureArray, PredictionsT],
        request: RegisteredPredictionRequest[FeatureArray],
        context: PredictionCaptureContext,
    ) -> RegisteredPredictionResult[PredictionsT]:
        """Preserve prediction outcome even when event persistence is unavailable."""
        started_at = utc_now()
        started_clock = perf_counter()
        observer = _ResolutionObserver()
        try:
            result = self._prediction_service.predict(
                plan,
                request,
                observer=observer,
            )
        except Exception as exc:
            duration_ms = _duration_ms(started_clock)
            completed_at = utc_now()
            await self._record_failure(
                plan=plan,
                request=request,
                context=context,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                prediction_error=exc,
                resolved_version=observer.version,
            )
            raise
        duration_ms = _duration_ms(started_clock)
        completed_at = utc_now()
        await self._record_success(
            request=request,
            context=context,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            result=result,
        )
        return result

    async def _record_success[
        PredictionsT: (RegressionPredictionArray | ClassificationPredictionArray),
    ](
        self,
        *,
        request: RegisteredPredictionRequest[FeatureArray],
        context: PredictionCaptureContext,
        started_at: datetime,
        completed_at: datetime,
        duration_ms: float,
        result: RegisteredPredictionResult[PredictionsT],
    ) -> None:
        try:
            reference = await self._event_store.get_reference_profile(
                result.model_version.registered_model_name,
                result.model_version.version,
            )
            event = PredictionEvent(
                id=uuid4(),
                requested_by_user_id=context.requested_by_user_id,
                registered_model_name=result.model_version.registered_model_name,
                requested_model_reference=request.version_or_alias,
                resolved_model_version=result.model_version.version,
                resolved_aliases=result.model_version.aliases,
                key=result.model_version.key,
                status=PredictionEventStatus.SUCCEEDED,
                row_count=request.features.shape[0],
                feature_count=request.features.shape[1],
                duration_ms=duration_ms,
                feature_profile=feature_request_profiles(request.features, reference),
                prediction_profile=prediction_request_profile(
                    result.predictions,
                    key=result.model_version.key,
                    reference=reference,
                ),
                error_code=None,
                safe_error_message=None,
                correlation_id=context.correlation_id,
                created_at=started_at,
                completed_at=completed_at,
            )
            await self._event_store.create_event(event)
            await self._event_store.commit()
        except Exception:
            await self._handle_persistence_failure()

    async def _record_failure[
        ModelT, PredictionsT
    ](
        self,
        *,
        plan: RegisteredPredictionPlan[ModelT, FeatureArray, PredictionsT],
        request: RegisteredPredictionRequest[FeatureArray],
        context: PredictionCaptureContext,
        started_at: datetime,
        completed_at: datetime,
        duration_ms: float,
        prediction_error: Exception,
        resolved_version: RegisteredModelVersion | None,
    ) -> None:
        row_count = request.features.shape[0] if request.features.ndim >= 1 else 0
        feature_count = request.features.shape[1] if request.features.ndim == 2 else 0
        error_code, safe_message = _safe_prediction_failure(prediction_error)
        try:
            event = PredictionEvent(
                id=uuid4(),
                requested_by_user_id=context.requested_by_user_id,
                registered_model_name=request.registered_model_name,
                requested_model_reference=request.version_or_alias,
                resolved_model_version=(
                    resolved_version.version if resolved_version is not None else None
                ),
                resolved_aliases=(
                    resolved_version.aliases if resolved_version is not None else ()
                ),
                key=resolved_version.key if resolved_version is not None else plan.key,
                status=PredictionEventStatus.FAILED,
                row_count=row_count,
                feature_count=feature_count,
                duration_ms=duration_ms,
                feature_profile=feature_request_profiles(request.features, None),
                prediction_profile=None,
                error_code=error_code,
                safe_error_message=safe_message,
                correlation_id=context.correlation_id,
                created_at=started_at,
                completed_at=completed_at,
            )
            await self._event_store.create_event(event)
            await self._event_store.commit()
        except Exception:
            await self._handle_persistence_failure()

    async def _handle_persistence_failure(self) -> None:
        self._capture_health.record_persistence_failure()
        logger.exception(
            "Prediction monitoring persistence failed; prediction was not retried.",
        )
        try:
            await self._event_store.rollback()
        except Exception:
            logger.exception("Prediction monitoring rollback also failed.")


def _safe_prediction_failure(error: Exception) -> tuple[str, str]:
    if isinstance(error, RegisteredModelVersionNotFoundError):
        return "model_version_not_found", "The requested model version was not found."
    if isinstance(error, ModelRegistryValidationError):
        return "model_reference_invalid", "The model reference was invalid."
    if isinstance(error, PredictionTrainerKeyMismatchError):
        return "trainer_key_mismatch", "The registered model task did not match."
    if isinstance(error, RegistryMetadataError):
        return "registry_metadata_invalid", "Registered model metadata was invalid."
    if isinstance(error, RegisteredModelTypeMismatchError):
        return "model_type_mismatch", "The fitted model type did not match."
    if isinstance(error, RegisteredModelLoadError):
        return "model_load_failed", "The registered model could not be loaded."
    if isinstance(error, ModelRegistryError):
        return "model_registry_unavailable", "The model registry was unavailable."
    if isinstance(error, TrainerDataValidationError):
        return "feature_validation_failed", "Prediction features were rejected."
    return "prediction_execution_failed", "Prediction execution failed."


def _duration_ms(started_clock: float) -> float:
    return max((perf_counter() - started_clock) * 1000.0, 0.0)

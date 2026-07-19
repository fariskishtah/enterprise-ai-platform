"""Ground-truth ingestion, maturity filtering, and bounded performance metrics."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.ml.domain import TaskType
from app.ml.monitoring.evaluation_models import (
    ClassificationPerformanceSummary,
    MaturePredictionOutcome,
    PerformanceSummary,
    PredictionOutcome,
    PredictionOutcomeType,
    RegressionPerformanceSummary,
)
from app.ml.monitoring.exceptions import (
    MonitoringNotFoundError,
    MonitoringPersistenceError,
    MonitoringPreconditionError,
)
from app.ml.monitoring.models import (
    ClassificationPredictionProfile,
    PredictionEvent,
    PredictionEventStatus,
    RegressionPredictionProfile,
)
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.repositories.prediction_outcomes import PredictionOutcomeRepository
from app.utils.security import utc_now


class PredictionOutcomeService:
    def __init__(
        self,
        *,
        repository: PredictionOutcomeRepository,
        monitoring_repository: PredictionMonitoringRepository,
        maximum_outcomes_per_summary: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._monitoring_repository = monitoring_repository
        self._maximum_outcomes = maximum_outcomes_per_summary
        self._clock = clock

    async def upsert(
        self,
        *,
        prediction_event_id: UUID,
        actual_value: float | int,
        observed_at: datetime,
        source: str,
        label_maturity_at: datetime,
        safe_metadata: Mapping[str, str],
        external_reference_key: str | None,
    ) -> PredictionOutcome:
        observed_at = _aware(observed_at)
        label_maturity_at = _aware(label_maturity_at)
        if label_maturity_at < observed_at:
            raise MonitoringPreconditionError(
                "Label maturity cannot precede the observed timestamp."
            )
        try:
            event = await self._monitoring_repository.get_event(prediction_event_id)
            existing = await self._repository.get_by_event(prediction_event_id)
            external = (
                await self._repository.get_by_external_reference(external_reference_key)
                if external_reference_key is not None
                else None
            )
        except SQLAlchemyError as exc:
            await self._repository.rollback()
            raise MonitoringPersistenceError(
                "Prediction outcome storage is unavailable."
            ) from exc
        if event is None:
            raise MonitoringNotFoundError("Prediction event was not found.")
        if external is not None and (existing is None or external.id != existing.id):
            raise MonitoringPreconditionError(
                "The external outcome reference is already in use."
            )
        outcome_type = _validate_event_and_value(event, actual_value)
        now = self._clock()
        outcome = PredictionOutcome(
            id=existing.id if existing is not None else uuid4(),
            prediction_event_id=prediction_event_id,
            outcome_type=outcome_type,
            actual_value=actual_value,
            observed_at=observed_at,
            source=source,
            label_maturity_at=label_maturity_at,
            safe_metadata=safe_metadata,
            external_reference_key=external_reference_key,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        try:
            persisted: PredictionOutcome | None
            if existing is None:
                persisted = await self._repository.create(outcome)
            else:
                persisted = await self._repository.update(outcome)
                if persisted is None:
                    raise MonitoringPersistenceError(
                        "Prediction outcome update failed."
                    )
            await self._repository.commit()
            assert persisted is not None
            return persisted
        except IntegrityError as exc:
            await self._repository.rollback()
            raise MonitoringPreconditionError(
                "A prediction outcome already exists for this reference."
            ) from exc
        except SQLAlchemyError as exc:
            await self._repository.rollback()
            raise MonitoringPersistenceError(
                "Prediction outcome storage is unavailable."
            ) from exc

    async def mature_outcomes(
        self, *, registered_model_name: str, model_version: str
    ) -> tuple[MaturePredictionOutcome, ...]:
        try:
            rows = await self._repository.list_mature(
                registered_model_name=registered_model_name,
                model_version=model_version,
                mature_at=self._clock(),
                limit=self._maximum_outcomes,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Prediction outcome storage is unavailable."
            ) from exc
        return tuple(
            MaturePredictionOutcome(
                outcome=outcome,
                registered_model_name=event.registered_model_name,
                model_version=event.resolved_model_version or "",
                key=event.key,
                predicted_value=_predicted_value(event),
            )
            for outcome, event in rows
        )

    async def performance_summary(
        self, *, registered_model_name: str, model_version: str
    ) -> PerformanceSummary:
        outcomes = await self.mature_outcomes(
            registered_model_name=registered_model_name,
            model_version=model_version,
        )
        if not outcomes:
            raise MonitoringPreconditionError(
                "No mature outcomes with exact retained predictions are available."
            )
        task = outcomes[0].key.task_type
        if any(item.key.task_type is not task for item in outcomes):
            raise MonitoringPreconditionError(
                "Mature outcome task types are inconsistent."
            )
        if task is TaskType.REGRESSION:
            return _regression_summary(registered_model_name, model_version, outcomes)
        return _classification_summary(registered_model_name, model_version, outcomes)


def _validate_event_and_value(
    event: PredictionEvent, actual_value: float | int
) -> PredictionOutcomeType:
    if event.status is not PredictionEventStatus.SUCCEEDED:
        raise MonitoringPreconditionError(
            "Outcomes can be attached only to successful prediction events."
        )
    if event.row_count != 1:
        raise MonitoringPreconditionError(
            "One outcome can be attached only to a single-row prediction event."
        )
    if isinstance(actual_value, bool):
        raise MonitoringPreconditionError("Prediction outcome value is invalid.")
    if event.key.task_type is TaskType.CLASSIFICATION:
        if not isinstance(actual_value, int):
            raise MonitoringPreconditionError(
                "Classification outcomes require an integer label."
            )
        return PredictionOutcomeType.CLASSIFICATION
    if not math.isfinite(float(actual_value)):
        raise MonitoringPreconditionError("Regression outcomes must be finite.")
    return PredictionOutcomeType.REGRESSION


def _predicted_value(event: PredictionEvent) -> float | int:
    profile = event.prediction_profile
    if event.row_count != 1:
        raise MonitoringPreconditionError(
            "Performance requires single-row prediction events."
        )
    if isinstance(profile, RegressionPredictionProfile):
        if profile.summary.mean is None:
            raise MonitoringPreconditionError(
                "The retained regression summary has no exact prediction."
            )
        return profile.summary.mean
    if isinstance(profile, ClassificationPredictionProfile):
        labels = [label for label, count in profile.class_counts.items() if count == 1]
        if profile.other_count or len(labels) != 1:
            raise MonitoringPreconditionError(
                "The retained classification summary has no exact prediction."
            )
        try:
            prefix, raw_label = labels[0].split(":", maxsplit=1)
            if prefix != "label":
                raise ValueError
            return int(raw_label)
        except ValueError as exc:
            raise MonitoringPreconditionError(
                "The retained classification label is invalid."
            ) from exc
    raise MonitoringPreconditionError(
        "The prediction event does not retain enough information for performance."
    )


def _regression_summary(
    name: str,
    version: str,
    outcomes: tuple[MaturePredictionOutcome, ...],
) -> RegressionPerformanceSummary:
    errors = [
        float(item.predicted_value) - float(item.outcome.actual_value)
        for item in outcomes
    ]
    count = len(errors)
    return RegressionPerformanceSummary(
        registered_model_name=name,
        model_version=version,
        evaluated_sample_count=count,
        mae=sum(abs(error) for error in errors) / count,
        rmse=math.sqrt(sum(error * error for error in errors) / count),
        mean_prediction_bias=sum(errors) / count,
    )


def _classification_summary(
    name: str,
    version: str,
    outcomes: tuple[MaturePredictionOutcome, ...],
) -> ClassificationPerformanceSummary:
    pairs = [
        (int(item.predicted_value), int(item.outcome.actual_value)) for item in outcomes
    ]
    labels = {value for pair in pairs for value in pair}
    if not labels <= {0, 1}:
        raise MonitoringPreconditionError(
            "Confusion-matrix performance currently supports binary labels 0 and 1."
        )
    tp = sum(predicted == 1 and actual == 1 for predicted, actual in pairs)
    tn = sum(predicted == 0 and actual == 0 for predicted, actual in pairs)
    fp = sum(predicted == 1 and actual == 0 for predicted, actual in pairs)
    fn = sum(predicted == 0 and actual == 1 for predicted, actual in pairs)
    count = len(pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ClassificationPerformanceSummary(
        registered_model_name=name,
        model_version=version,
        evaluated_sample_count=count,
        accuracy=(tp + tn) / count,
        precision=precision,
        recall=recall,
        f1=f1,
        false_negative_rate=fn / (fn + tp) if fn + tp else 0.0,
        true_positive_count=tp,
        true_negative_count=tn,
        false_positive_count=fp,
        false_negative_count=fn,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonitoringPreconditionError(
            "Prediction outcome timestamps must include a UTC offset."
        )
    return value

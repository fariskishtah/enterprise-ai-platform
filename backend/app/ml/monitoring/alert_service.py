"""Internal alert lifecycle derived from persisted monitoring evaluations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringAlert,
    MonitoringAlertPage,
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
    MonitoringEvaluationStatus,
    monitoring_alert_deduplication_key,
)
from app.ml.monitoring.exceptions import (
    MonitoringNotFoundError,
    MonitoringPersistenceError,
    MonitoringPreconditionError,
)
from app.observability.metrics import record_monitoring_alert_resolved
from app.repositories.monitoring_alerts import MonitoringAlertRepository
from app.utils.security import utc_now

_ALERT_COPY: dict[MonitoringAlertType, tuple[MonitoringAlertSeverity, str, str]] = {
    MonitoringAlertType.FEATURE_DRIFT: (
        MonitoringAlertSeverity.CRITICAL,
        "Critical feature drift detected",
        "One or more feature distributions exceeded the critical drift threshold.",
    ),
    MonitoringAlertType.PREDICTION_DRIFT: (
        MonitoringAlertSeverity.CRITICAL,
        "Critical prediction drift detected",
        "The prediction distribution exceeded the critical drift threshold.",
    ),
    MonitoringAlertType.HIGH_FAILURE_RATE: (
        MonitoringAlertSeverity.CRITICAL,
        "High prediction failure rate",
        "The bounded evaluation window contains a critical prediction failure rate.",
    ),
    MonitoringAlertType.MISSING_REFERENCE_PROFILE: (
        MonitoringAlertSeverity.CRITICAL,
        "Missing monitoring reference profile",
        "The exact registered model version has no trusted reference profile.",
    ),
    MonitoringAlertType.INSUFFICIENT_DATA: (
        MonitoringAlertSeverity.WARNING,
        "Insufficient recent prediction data",
        "Recent successful predictions do not meet the configured sample minimum.",
    ),
    MonitoringAlertType.EVALUATION_FAILURE: (
        MonitoringAlertSeverity.CRITICAL,
        "Monitoring evaluation unavailable",
        "Required bounded monitoring inputs could not be evaluated safely.",
    ),
    MonitoringAlertType.PERSISTENCE_FAILURE: (
        MonitoringAlertSeverity.WARNING,
        "Prediction event persistence failures observed",
        "The current API instance reported prediction-event persistence failures.",
    ),
    MonitoringAlertType.NO_RECENT_PREDICTIONS: (
        MonitoringAlertSeverity.WARNING,
        "No recent predictions",
        "No completed prediction attempts were found for this active model version.",
    ),
}


@dataclass(frozen=True, slots=True)
class MonitoringAlertChanges:
    detected: tuple[MonitoringAlert, ...]
    created: tuple[MonitoringAlert, ...]
    resolved: tuple[MonitoringAlert, ...]


class MonitoringAlertService:
    def __init__(
        self,
        *,
        repository: MonitoringAlertRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def process_evaluation(
        self, evaluation: ModelMonitoringEvaluation
    ) -> MonitoringAlertChanges:
        """Upsert active conditions and resolve conditions cleared by this result."""
        detected = _conditions(evaluation)
        alerts: list[MonitoringAlert] = []
        created: list[MonitoringAlert] = []
        now = self._clock()
        try:
            for alert_type in detected:
                alert, was_created = await self._upsert(evaluation, alert_type, now)
                alerts.append(alert)
                if was_created:
                    created.append(alert)
            cleared = frozenset(MonitoringAlertType) - detected
            resolved = await self._repository.resolve_types(
                registered_model_name=evaluation.registered_model_name,
                model_version=evaluation.model_version,
                alert_types=cleared,
                resolved_at=now,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Monitoring alert storage is unavailable."
            ) from exc
        return MonitoringAlertChanges(tuple(alerts), tuple(created), resolved)

    async def _upsert(
        self,
        evaluation: ModelMonitoringEvaluation,
        alert_type: MonitoringAlertType,
        now: datetime,
    ) -> tuple[MonitoringAlert, bool]:
        severity, title, summary = _ALERT_COPY[alert_type]
        key = monitoring_alert_deduplication_key(
            alert_type=alert_type,
            registered_model_name=evaluation.registered_model_name,
            model_version=evaluation.model_version,
        )
        existing = await self._repository.get_by_deduplication(key)
        if existing is not None:
            updated = await self._repository.redetect(
                alert_id=existing.id,
                severity=severity,
                monitoring_evaluation_id=evaluation.id,
                detected_at=now,
                title=title,
                safe_summary=summary,
            )
            if updated is None:
                raise MonitoringPersistenceError("Monitoring alert update failed.")
            return updated, False
        created = await self._repository.create(
            MonitoringAlert(
                id=uuid4(),
                alert_type=alert_type,
                severity=severity,
                registered_model_name=evaluation.registered_model_name,
                model_version=evaluation.model_version,
                monitoring_evaluation_id=evaluation.id,
                title=title,
                safe_summary=summary,
                deduplication_key=key,
                status=MonitoringAlertStatus.OPEN,
                first_detected_at=now,
                last_detected_at=now,
                occurrence_count=1,
                acknowledged_at=None,
                acknowledged_by_user_id=None,
                resolved_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        return created, True

    async def get(self, alert_id: UUID) -> MonitoringAlert:
        try:
            alert = await self._repository.get(alert_id)
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Monitoring alert storage is unavailable."
            ) from exc
        if alert is None:
            raise MonitoringNotFoundError("Monitoring alert was not found.")
        return alert

    async def list(
        self,
        *,
        registered_model_name: str | None,
        model_version: str | None,
        severity: MonitoringAlertSeverity | None,
        status: MonitoringAlertStatus | None,
        limit: int,
        offset: int,
    ) -> MonitoringAlertPage:
        try:
            return await self._repository.list(
                registered_model_name=registered_model_name,
                model_version=model_version,
                severity=severity,
                status=status,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError as exc:
            raise MonitoringPersistenceError(
                "Monitoring alert storage is unavailable."
            ) from exc

    async def acknowledge(self, alert_id: UUID, actor_id: UUID) -> MonitoringAlert:
        now = self._clock()
        try:
            alert = await self._repository.acknowledge(
                alert_id=alert_id, actor_id=actor_id, acknowledged_at=now
            )
            if alert is None:
                existing = await self._repository.get(alert_id)
                if existing is None:
                    raise MonitoringNotFoundError("Monitoring alert was not found.")
                raise MonitoringPreconditionError(
                    "Only an open monitoring alert can be acknowledged."
                )
            await self._repository.commit()
            return alert
        except SQLAlchemyError as exc:
            await self._repository.rollback()
            raise MonitoringPersistenceError(
                "Monitoring alert storage is unavailable."
            ) from exc

    async def resolve(self, alert_id: UUID) -> MonitoringAlert:
        now = self._clock()
        try:
            alert = await self._repository.resolve(alert_id=alert_id, resolved_at=now)
            if alert is None:
                existing = await self._repository.get(alert_id)
                if existing is None:
                    raise MonitoringNotFoundError("Monitoring alert was not found.")
                return existing
            await self._repository.commit()
            record_monitoring_alert_resolved(
                alert_type=alert.alert_type.value,
                severity=alert.severity.value,
            )
            return alert
        except SQLAlchemyError as exc:
            await self._repository.rollback()
            raise MonitoringPersistenceError(
                "Monitoring alert storage is unavailable."
            ) from exc


def _conditions(
    evaluation: ModelMonitoringEvaluation,
) -> frozenset[MonitoringAlertType]:
    values: set[MonitoringAlertType] = set()
    if evaluation.feature_drift_status is MonitoringEvaluationStatus.CRITICAL:
        values.add(MonitoringAlertType.FEATURE_DRIFT)
    if evaluation.prediction_drift_status is MonitoringEvaluationStatus.CRITICAL:
        values.add(MonitoringAlertType.PREDICTION_DRIFT)
    if evaluation.operational_health_status is MonitoringEvaluationStatus.CRITICAL:
        values.add(MonitoringAlertType.HIGH_FAILURE_RATE)
    availability = evaluation.report.get("availability")
    error_code = (
        availability.get("error_code") if isinstance(availability, dict) else None
    )
    if error_code == "missing_reference_profile":
        values.add(MonitoringAlertType.MISSING_REFERENCE_PROFILE)
    elif evaluation.overall_status is MonitoringEvaluationStatus.UNAVAILABLE:
        values.add(MonitoringAlertType.EVALUATION_FAILURE)
    if evaluation.overall_status is MonitoringEvaluationStatus.INSUFFICIENT_DATA:
        values.add(MonitoringAlertType.INSUFFICIENT_DATA)
    if evaluation.successful_prediction_count + evaluation.failed_prediction_count == 0:
        values.add(MonitoringAlertType.NO_RECENT_PREDICTIONS)
    operational = evaluation.report.get("operational")
    capture_failures = (
        operational.get("instance_capture_failures_since_start", 0)
        if isinstance(operational, dict)
        else 0
    )
    if isinstance(capture_failures, int) and capture_failures > 0:
        values.add(MonitoringAlertType.PERSISTENCE_FAILURE)
    return frozenset(values)

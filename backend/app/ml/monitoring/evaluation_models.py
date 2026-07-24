"""Immutable orchestration records for persisted monitoring and outcomes."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from uuid import UUID

from app.ml.base import TrainerKey


class MonitoringEvaluationStatus(StrEnum):
    """Stable component and aggregate states for one evaluation."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    INSUFFICIENT_DATA = "insufficient_data"
    UNAVAILABLE = "unavailable"


class MonitoringEvaluationTrigger(StrEnum):
    """Supported initiators of a persisted evaluation."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    RECONCILIATION = "reconciliation"


class MonitoringAlertType(StrEnum):
    """Privacy-safe internal conditions that can be deduplicated."""

    FEATURE_DRIFT = "critical_feature_drift"
    PREDICTION_DRIFT = "critical_prediction_drift"
    HIGH_FAILURE_RATE = "high_prediction_failure_rate"
    MISSING_REFERENCE_PROFILE = "missing_reference_profile"
    INSUFFICIENT_DATA = "insufficient_recent_prediction_data"
    EVALUATION_FAILURE = "monitoring_evaluation_failure"
    PERSISTENCE_FAILURE = "prediction_event_persistence_failure"
    NO_RECENT_PREDICTIONS = "no_recent_predictions"
    MACHINE_RISK = "machine_risk_indication"


class MonitoringAlertSeverity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class MonitoringAlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class PredictionOutcomeType(StrEnum):
    REGRESSION = "regression"
    CLASSIFICATION = "classification"


@dataclass(frozen=True, slots=True)
class ModelMonitoringEvaluation:
    """One immutable exact-version monitoring result and its safe report."""

    id: UUID
    registered_model_name: str
    model_version: str
    model_alias: str | None
    key: TrainerKey
    window_start: datetime
    window_end: datetime
    evaluated_sample_count: int
    successful_prediction_count: int
    failed_prediction_count: int
    data_quality_status: MonitoringEvaluationStatus
    feature_drift_status: MonitoringEvaluationStatus
    prediction_drift_status: MonitoringEvaluationStatus
    operational_health_status: MonitoringEvaluationStatus
    overall_status: MonitoringEvaluationStatus
    report_schema_version: str
    report: Mapping[str, object]
    warning_count: int
    critical_count: int
    trigger: MonitoringEvaluationTrigger
    idempotency_key: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.registered_model_name or not self.model_version:
            raise ValueError("Monitoring evaluation model identity is required.")
        if self.window_start >= self.window_end:
            raise ValueError("Monitoring evaluation window is invalid.")
        if (
            min(
                self.evaluated_sample_count,
                self.successful_prediction_count,
                self.failed_prediction_count,
                self.warning_count,
                self.critical_count,
            )
            < 0
        ):
            raise ValueError("Monitoring evaluation counts must be non-negative.")
        if not self.report_schema_version or not self.idempotency_key:
            raise ValueError("Monitoring report and idempotency versions are required.")
        object.__setattr__(self, "report", MappingProxyType(dict(self.report)))


@dataclass(frozen=True, slots=True)
class MonitoringEvaluationPage:
    items: tuple[ModelMonitoringEvaluation, ...]
    total: int


@dataclass(frozen=True, slots=True)
class MonitoringAlert:
    """Deduplicated internal alert without raw exception or prediction data."""

    id: UUID
    alert_type: MonitoringAlertType
    severity: MonitoringAlertSeverity
    registered_model_name: str
    model_version: str
    monitoring_evaluation_id: UUID | None
    title: str
    safe_summary: str
    deduplication_key: str
    status: MonitoringAlertStatus
    first_detected_at: datetime
    last_detected_at: datetime
    occurrence_count: int
    acknowledged_at: datetime | None
    acknowledged_by_user_id: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    factory_id: UUID | None = None
    machine_id: UUID | None = None
    operator_note: str | None = None
    engineer_note: str | None = None
    cooldown_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class MonitoringAlertPage:
    items: tuple[MonitoringAlert, ...]
    total: int


@dataclass(frozen=True, slots=True)
class PredictionOutcome:
    """One observed target linked to a privacy-safe prediction event."""

    id: UUID
    prediction_event_id: UUID
    outcome_type: PredictionOutcomeType
    actual_value: float | int
    observed_at: datetime
    source: str
    label_maturity_at: datetime
    safe_metadata: Mapping[str, str]
    external_reference_key: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.source.strip() or len(self.source) > 128:
            raise ValueError("Prediction outcome source is invalid.")
        if isinstance(self.actual_value, bool):
            raise ValueError("Prediction outcome values cannot be boolean.")
        if self.outcome_type is PredictionOutcomeType.CLASSIFICATION:
            if not isinstance(self.actual_value, int):
                raise ValueError("Classification outcomes require an integer label.")
        elif not math.isfinite(float(self.actual_value)):
            raise ValueError("Regression outcomes must be finite.")
        copied = dict(self.safe_metadata)
        if len(copied) > 16 or any(
            not key or len(key) > 64 or len(value) > 256
            for key, value in copied.items()
        ):
            raise ValueError("Prediction outcome metadata exceeds safe bounds.")
        object.__setattr__(self, "safe_metadata", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class MaturePredictionOutcome:
    outcome: PredictionOutcome
    registered_model_name: str
    model_version: str
    key: TrainerKey
    predicted_value: float | int


@dataclass(frozen=True, slots=True)
class RegressionPerformanceSummary:
    registered_model_name: str
    model_version: str
    evaluated_sample_count: int
    mae: float
    rmse: float
    mean_prediction_bias: float


@dataclass(frozen=True, slots=True)
class ClassificationPerformanceSummary:
    registered_model_name: str
    model_version: str
    evaluated_sample_count: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    false_negative_rate: float
    true_positive_count: int
    true_negative_count: int
    false_positive_count: int
    false_negative_count: int


type PerformanceSummary = (
    RegressionPerformanceSummary | ClassificationPerformanceSummary
)


def monitoring_evaluation_idempotency_key(
    *,
    registered_model_name: str,
    model_version: str,
    window_start: datetime,
    window_end: datetime,
) -> str:
    """Hash the immutable model and exact UTC evaluation window."""
    canonical = json.dumps(
        {
            "model": registered_model_name,
            "version": model_version,
            "window_end": window_end.isoformat(),
            "window_start": window_start.isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def monitoring_alert_deduplication_key(
    *, alert_type: MonitoringAlertType, registered_model_name: str, model_version: str
) -> str:
    canonical = f"{alert_type.value}:{registered_model_name}:{model_version}"
    return sha256(canonical.encode("utf-8")).hexdigest()

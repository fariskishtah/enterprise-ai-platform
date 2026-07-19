"""API contracts for persisted evaluations, alerts, and prediction outcomes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt

from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
    PredictionOutcomeType,
)


class MonitoringEvaluationResponse(BaseModel):
    id: UUID
    registered_model_name: str
    model_version: str
    model_alias: str | None
    algorithm: AlgorithmType
    task_type: TaskType
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
    report: dict[str, object]
    warning_count: int
    critical_count: int
    trigger: MonitoringEvaluationTrigger
    created_at: datetime
    updated_at: datetime


class MonitoringEvaluationPageResponse(BaseModel):
    items: tuple[MonitoringEvaluationResponse, ...]
    total: int
    limit: int
    offset: int


class ManualMonitoringEvaluationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_start: datetime | None = None
    window_end: datetime | None = None


class MonitoringAlertResponse(BaseModel):
    id: UUID
    alert_type: MonitoringAlertType
    severity: MonitoringAlertSeverity
    registered_model_name: str
    model_version: str
    monitoring_evaluation_id: UUID | None
    title: str
    safe_summary: str
    status: MonitoringAlertStatus
    first_detected_at: datetime
    last_detected_at: datetime
    occurrence_count: int
    acknowledged_at: datetime | None
    acknowledged_by_user_id: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MonitoringAlertPageResponse(BaseModel):
    items: tuple[MonitoringAlertResponse, ...]
    total: int
    limit: int
    offset: int


class PredictionOutcomeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_value: StrictInt | StrictFloat
    observed_at: datetime
    source: str = Field(min_length=1, max_length=128)
    label_maturity_at: datetime
    safe_metadata: dict[
        Annotated[str, Field(min_length=1, max_length=64)],
        Annotated[str, Field(max_length=256)],
    ] = Field(default_factory=dict, max_length=16)
    external_reference_key: str | None = Field(
        default=None, min_length=1, max_length=128
    )


class PredictionOutcomeResponse(BaseModel):
    id: UUID
    prediction_event_id: UUID
    outcome_type: PredictionOutcomeType
    actual_value: int | float
    observed_at: datetime
    source: str
    label_maturity_at: datetime
    safe_metadata: dict[str, str]
    external_reference_key: str | None
    created_at: datetime
    updated_at: datetime


class RegressionPerformanceResponse(BaseModel):
    registered_model_name: str
    model_version: str
    task_type: TaskType = TaskType.REGRESSION
    evaluated_sample_count: int
    mae: float
    rmse: float
    mean_prediction_bias: float


class ClassificationPerformanceResponse(BaseModel):
    registered_model_name: str
    model_version: str
    task_type: TaskType = TaskType.CLASSIFICATION
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


type PerformanceResponse = (
    RegressionPerformanceResponse | ClassificationPerformanceResponse
)

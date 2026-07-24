"""Public contracts for guided onboarding, live demo, and reporting."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

SafeKey = Annotated[
    str, StringConstraints(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
]


class ImportShape(StrEnum):
    LONG = "long"
    WIDE = "wide"


class ImportMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    shape: ImportShape
    timestamp: str = Field(min_length=1, max_length=255)
    machine: str = Field(min_length=1, max_length=255)
    sensor: str | None = Field(default=None, min_length=1, max_length=255)
    value: str | None = Field(default=None, min_length=1, max_length=255)
    features: list[str] = Field(default_factory=list, max_length=128)
    target: str | None = Field(default=None, min_length=1, max_length=255)
    operating_state: str | None = Field(default=None, min_length=1, max_length=255)
    batch_or_shift: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_shape(self) -> ImportMapping:
        if self.shape == ImportShape.LONG and (not self.sensor or not self.value):
            raise ValueError("Long format requires sensor and value columns.")
        if self.shape == ImportShape.WIDE and not self.features:
            raise ValueError("Wide format requires at least one feature column.")
        columns = [
            self.timestamp,
            self.machine,
            self.sensor,
            self.value,
            self.target,
            self.operating_state,
            self.batch_or_shift,
            *self.features,
        ]
        values = [item.casefold() for item in columns if item]
        if len(values) != len(set(values)):
            raise ValueError("A source column cannot be mapped more than once.")
        return self


class QualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: str
    count: int = Field(ge=0)
    meaning: str
    correction: str
    samples: list[int] = Field(default_factory=list, max_length=20)


class DataImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    filename: str
    media_type: str
    size_bytes: int
    status: str
    delimiter: str
    has_header: bool
    mapping: dict[str, object]
    preview: list[dict[str, object]]
    quality_report: dict[str, object]
    error_samples: list[dict[str, object]]
    total_rows: int
    imported_rows: int
    rejected_rows: int
    progress_percent: int
    warnings_accepted: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ImportListResponse(BaseModel):
    items: list[DataImportResponse]
    total: int
    limit: int
    offset: int


class ImportMappingRequest(BaseModel):
    mapping: ImportMapping
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    has_header: bool = True


class ConfirmImportRequest(BaseModel):
    accept_warnings: bool = False


class GuidedUseCase(StrEnum):
    PREDICTIVE_MAINTENANCE = "predictive_maintenance"
    ENERGY_MONITORING = "energy_monitoring"
    QUALITY_PREDICTION = "quality_prediction"
    CONDITION_MONITORING = "condition_monitoring"


class TrainingProfile(StrEnum):
    FAST_DEMO = "fast_demo"
    BALANCED = "balanced"
    THOROUGH = "thorough"


class GuidedTemplateResponse(BaseModel):
    use_case: GuidedUseCase
    label: str
    task_type: str
    supported_profiles: list[TrainingProfile]
    limitation: str | None = None


class ReadinessRequest(BaseModel):
    import_id: UUID
    use_case: GuidedUseCase
    target: str | None = None
    features: list[str] = Field(min_length=1, max_length=128)
    profile: TrainingProfile


class ReadinessResponse(BaseModel):
    ready: bool
    dataset_size: int
    valid_rows: int
    selected_features: list[str]
    target_available: bool
    missingness_rate: float
    time_coverage: str | None
    blocking_issues: list[str]
    profile_summary: str
    deployment_consequence: str


class DemoScenarioName(StrEnum):
    NORMAL = "normal_operation"
    DEGRADATION = "gradual_degradation"
    WARNING = "warning_threshold"
    CRITICAL = "critical_condition"
    SENSOR_FAULT = "sensor_fault"
    DATA_DROPOUT = "data_dropout"
    MAINTENANCE = "maintenance_intervention"
    RECOVERY = "recovery_to_normal"


class DemoScenarioStart(BaseModel):
    factory_id: UUID
    machine_id: UUID
    scenario: DemoScenarioName
    speed: int = Field(default=1)
    idempotency_key: SafeKey

    @model_validator(mode="after")
    def validate_speed(self) -> DemoScenarioStart:
        if self.speed not in {1, 2, 5}:
            raise ValueError("Speed must be 1x, 2x, or 5x.")
        return self


class DemoScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    factory_id: UUID
    machine_id: UUID
    scenario: str
    status: str
    speed: int
    current_step: int
    generated_readings: int
    state_snapshot: dict[str, object]
    started_at: datetime
    updated_at: datetime
    stopped_at: datetime | None


class LayoutNode(BaseModel):
    machine_id: UUID
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    group: str | None = Field(default=None, max_length=64)


class FactoryLayoutUpdate(BaseModel):
    nodes: list[LayoutNode] = Field(max_length=200)


class FactoryLayoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    factory_id: UUID
    nodes: list[dict[str, object]]
    version: int
    updated_at: datetime


class ReportType(StrEnum):
    EXECUTIVE_FACTORY = "executive_factory_summary"
    MACHINE_HEALTH = "machine_health"
    ALERT_ACTION = "alert_and_action"
    SHIFT_HANDOVER = "shift_handover"
    DATA_QUALITY = "data_quality"
    MODEL_GOVERNANCE = "model_and_prediction_governance"


class ReportFormat(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"
    CSV = "csv"


class ReportCreate(BaseModel):
    report_type: ReportType
    format: ReportFormat
    factory_id: UUID | None = None
    period_start: datetime
    period_end: datetime
    idempotency_key: SafeKey


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    factory_id: UUID | None
    report_type: str
    format: str
    status: str
    period_start: datetime
    period_end: datetime
    size_bytes: int | None
    summary: dict[str, object]
    safe_error: str | None
    expires_at: datetime | None
    created_at: datetime
    completed_at: datetime | None


class ReportScheduleCreate(BaseModel):
    report_type: ReportType
    format: ReportFormat
    factory_id: UUID | None = None
    period: str = Field(
        pattern=r"^(current_shift|previous_shift|today|last_7_days|last_30_days)$"
    )
    cadence: str = Field(pattern=r"^(daily|weekly|monthly)$")
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    recipients: list[EmailStr] = Field(min_length=1, max_length=10)
    enabled: bool = False
    idempotency_key: SafeKey


class ReportScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    factory_id: UUID | None
    report_type: str
    format: str
    period: str
    cadence: str
    timezone: str
    recipients: list[str]
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_result: str | None
    last_error: str | None


class IncidentSummaryResponse(BaseModel):
    machine_id: UUID
    what_happened: str
    first_detected: datetime | None
    actions_taken: list[str]
    resolution: str
    current_status: str
    follow_up_recommendations: list[str]

"""Operational maintenance workflow API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.operations import (
    MaintenanceFeedbackOutcome,
    OperationalActionPriority,
    OperationalActionStatus,
    OperationalNoteKind,
    ShiftStatus,
)


class OperationalActionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factory_id: UUID
    machine_id: UUID
    related_alert_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)
    recommended_action: str = Field(min_length=1, max_length=2000)
    priority: OperationalActionPriority
    assigned_user_id: UUID | None = None
    due_at: datetime | None = None


class OperationalActionAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_user_id: UUID
    expected_version: int = Field(ge=1)


class OperationalActionAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class OperationalActionTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["in_progress", "blocked", "completed", "cancelled"]
    expected_version: int = Field(ge=1)
    summary: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def completion_requires_summary(self) -> "OperationalActionTransitionRequest":
        if self.status == "completed" and not (self.summary or "").strip():
            raise ValueError("A completion summary is required.")
        return self


class OperationalActionReopenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class OperationalActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    factory_id: UUID
    machine_id: UUID
    related_alert_id: UUID | None
    title: str
    reason: str
    recommended_action: str
    priority: OperationalActionPriority
    status: OperationalActionStatus
    assigned_user_id: UUID | None
    created_by: UUID
    due_at: datetime | None
    acknowledged_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    completion_summary: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class OperationalActionPageResponse(BaseModel):
    items: list[OperationalActionResponse]
    total: int
    limit: int
    offset: int


class OperationalNoteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)


class OperationalNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    factory_id: UUID
    machine_id: UUID
    action_id: UUID | None
    alert_id: UUID | None
    author_user_id: UUID
    kind: OperationalNoteKind
    body: str
    created_at: datetime


class MaintenanceFeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: UUID | None = None
    alert_id: UUID | None = None
    outcome: MaintenanceFeedbackOutcome
    maintenance_category: str | None = Field(default=None, max_length=128)
    replaced_component: str | None = Field(default=None, max_length=128)
    downtime_minutes: int | None = Field(default=None, ge=0, le=525_600)
    summary: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def at_least_one_parent(self) -> "MaintenanceFeedbackCreateRequest":
        if self.action_id is None and self.alert_id is None:
            raise ValueError("An action or alert is required.")
        return self


class MaintenanceFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    factory_id: UUID
    machine_id: UUID
    action_id: UUID | None
    alert_id: UUID | None
    outcome: MaintenanceFeedbackOutcome
    maintenance_category: str | None
    replaced_component: str | None
    downtime_minutes: int | None
    summary: str
    submitted_by_user_id: UUID
    created_at: datetime


class MaintenanceFeedbackPageResponse(BaseModel):
    items: list[MaintenanceFeedbackResponse]
    total: int
    limit: int
    offset: int


class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    factory_id: UUID
    machine_id: UUID
    action_id: UUID | None
    alert_id: UUID | None
    actor_user_id: UUID | None
    event_type: str
    title: str
    detail: str
    safe_metadata: dict[str, object]
    occurred_at: datetime


class TimelinePageResponse(BaseModel):
    items: list[TimelineEventResponse]
    total: int
    limit: int
    offset: int


class ShiftStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factory_id: UUID
    team_label: str | None = Field(default=None, max_length=128)


class ShiftEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handover_notes: str = Field(min_length=1, max_length=4000)
    unresolved_summary: str | None = Field(default=None, max_length=4000)


class ShiftAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledgement_note: str | None = Field(default=None, max_length=1000)


class ShiftHandoverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    factory_id: UUID
    status: ShiftStatus
    started_by_user_id: UUID
    ended_by_user_id: UUID | None
    acknowledged_by_user_id: UUID | None
    team_label: str | None
    handover_notes: str | None
    unresolved_summary: str | None
    snapshot: dict[str, object]
    started_at: datetime
    ended_at: datetime | None
    acknowledged_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ShiftPageResponse(BaseModel):
    items: list[ShiftHandoverResponse]
    total: int
    limit: int
    offset: int


class OperationalSearchResult(BaseModel):
    id: UUID
    resource_type: Literal[
        "factory", "machine", "sensor", "alert", "operational_action", "user"
    ]
    label: str
    description: str | None
    path: str


class OperationalSearchResponse(BaseModel):
    items: list[OperationalSearchResult]
    limit: int


class OperationalAssigneeResponse(BaseModel):
    id: UUID
    email: str
    role: str


class OperationalSummaryResponse(BaseModel):
    action_counts: dict[str, int]
    alert_counts: dict[str, int]
    risk_counts: dict[str, int]
    overdue_actions: int
    unassigned_urgent_actions: int
    active_shift_count: int
    data_freshness_seconds: float | None


class OperationalAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    factory_id: UUID | None
    machine_id: UUID | None
    title: str
    safe_summary: str
    severity: str
    status: str
    first_detected_at: datetime
    last_detected_at: datetime
    occurrence_count: int
    assigned_user_id: UUID | None
    assigned_at: datetime | None
    acknowledged_at: datetime | None
    in_progress_at: datetime | None
    escalated_at: datetime | None
    resolved_at: datetime | None
    resolution_summary: str | None
    resolution_classification: str | None
    reopened_at: datetime | None
    lifecycle_version: int


class OperationalAlertPageResponse(BaseModel):
    items: list[OperationalAlertResponse]
    total: int
    limit: int
    offset: int


class AlertLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition: Literal[
        "assign",
        "acknowledge",
        "start",
        "escalate",
        "resolve",
        "reopen",
    ]
    expected_version: int = Field(ge=1)
    assigned_user_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    resolution_summary: str | None = Field(default=None, max_length=2000)
    resolution_classification: (
        Literal[
            "true_issue",
            "false_alarm",
            "sensor_issue",
            "maintenance_performed",
            "no_action_required",
        ]
        | None
    ) = None
    reopen_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def required_transition_fields(self) -> "AlertLifecycleRequest":
        if self.transition == "assign" and self.assigned_user_id is None:
            raise ValueError("An assignee is required.")
        if self.transition == "resolve" and not (
            (self.resolution_summary or "").strip()
            and self.resolution_classification is not None
        ):
            raise ValueError("Resolution summary and classification are required.")
        if self.transition == "reopen" and not (self.reopen_reason or "").strip():
            raise ValueError("A reopen reason is required.")
        return self

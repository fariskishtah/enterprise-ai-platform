"""Immutable contracts for controlled, auditable model retraining."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from uuid import UUID

from app.ml.base import TrainerKey
from app.ml.monitoring import DriftSeverity


class RetrainingTriggerType(StrEnum):
    """Supported evidence sources; realized outcome labels are not yet available."""

    FEATURE_DRIFT = "feature_drift"
    PREDICTION_DRIFT = "prediction_drift"
    DATA_QUALITY = "data_quality"
    MANUAL = "manual"


class RetrainingDecisionStatus(StrEnum):
    """Stable outcomes from the ordered policy evaluation."""

    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    BLOCKED_COOLDOWN = "blocked_cooldown"
    BLOCKED_DUPLICATE = "blocked_duplicate"
    BLOCKED_QUOTA = "blocked_quota"
    BLOCKED_INSUFFICIENT_DATA = "blocked_insufficient_data"
    BLOCKED_MISSING_PROFILE = "blocked_missing_profile"
    BLOCKED_MISSING_TRAINING_EVIDENCE = "blocked_missing_training_evidence"
    DISABLED = "disabled"


class RetrainingRequestStatus(StrEnum):
    """Durable checkpoints around the existing background job lifecycle."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    TRAINING = "training"
    CANDIDATE_CREATED = "candidate_created"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetrainingEvaluationMode(StrEnum):
    """Whether drift policy or a named human initiated evaluation."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class ComparisonStatus(StrEnum):
    """Advisory relationship between source and candidate metrics."""

    BETTER = "better"
    WORSE = "worse"
    MIXED = "mixed"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True, slots=True)
class RetrainingPolicy:
    """One validated policy scoped to an exact registered-model name."""

    id: UUID
    registered_model_name: str
    enabled: bool
    allowed_trigger_types: frozenset[RetrainingTriggerType]
    minimum_drift_status: DriftSeverity
    minimum_current_sample_count: int
    cooldown_seconds: int
    maximum_requests_per_day: int
    maximum_requests_per_week: int
    maximum_active_requests: int
    require_champion_source: bool
    allow_truncated_drift: bool
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.registered_model_name.strip():
            raise ValueError("registered_model_name must not be empty.")
        if not self.allowed_trigger_types:
            raise ValueError("At least one retraining trigger type is required.")
        if self.minimum_drift_status not in {
            DriftSeverity.WARNING,
            DriftSeverity.CRITICAL,
        }:
            raise ValueError("minimum_drift_status must be warning or critical.")
        if self.minimum_current_sample_count <= 0:
            raise ValueError("minimum_current_sample_count must be positive.")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative.")
        if (
            min(
                self.maximum_requests_per_day,
                self.maximum_requests_per_week,
                self.maximum_active_requests,
            )
            <= 0
        ):
            raise ValueError("Retraining quotas must be positive.")

    @property
    def version_token(self) -> str:
        """Return the persisted update time used by trigger idempotency."""
        return _utc(self.updated_at).isoformat()


@dataclass(frozen=True, slots=True)
class RetrainingTrigger:
    """Bounded trigger identity and drift facts, never raw prediction events."""

    trigger_type: RetrainingTriggerType
    reference: str
    aggregate_status: DriftSeverity | None
    matched_event_count: int
    analyzed_event_count: int
    current_sample_count: int
    truncated: bool
    analysis_warning: str | None
    thresholds: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.reference.strip() or len(self.reference) > 512:
            raise ValueError("trigger reference must be between 1 and 512 characters.")
        if (
            min(
                self.matched_event_count,
                self.analyzed_event_count,
                self.current_sample_count,
            )
            < 0
        ):
            raise ValueError("Trigger sample counts must be non-negative.")
        object.__setattr__(self, "thresholds", MappingProxyType(dict(self.thresholds)))


@dataclass(frozen=True, slots=True)
class CooldownState:
    """Exact-model cooldown facts evaluated at one UTC instant."""

    active: bool
    started_at: datetime | None
    expires_at: datetime | None
    remaining_seconds: int


@dataclass(frozen=True, slots=True)
class QuotaState:
    """Persisted request counts and their configured limits."""

    requests_today: int
    requests_this_week: int
    active_requests: int
    maximum_per_day: int
    maximum_per_week: int
    maximum_active: int


@dataclass(frozen=True, slots=True)
class RetrainingDecision:
    """Complete, deterministic policy result suitable for an audit record."""

    registered_model_name: str
    source_model_version: str | None
    requested_alias: str | None
    trigger: RetrainingTrigger
    status: RetrainingDecisionStatus
    reasons: tuple[str, ...]
    evaluated_at: datetime
    cooldown: CooldownState
    quota: QuotaState
    existing_request_id: UUID | None = None

    @property
    def eligible(self) -> bool:
        return self.status is RetrainingDecisionStatus.ELIGIBLE


@dataclass(frozen=True, slots=True)
class RetrainingRequest:
    """Repository-owned retraining lineage and execution snapshot."""

    id: UUID
    registered_model_name: str
    source_model_version: str
    source_training_job_id: UUID
    key: TrainerKey
    trigger_type: RetrainingTriggerType
    trigger_reference: str
    policy_id: UUID
    decision_status: RetrainingDecisionStatus
    request_status: RetrainingRequestStatus
    evaluation_mode: RetrainingEvaluationMode
    idempotency_key: str
    training_job_id: UUID | None
    resulting_model_version: str | None
    requested_by_user_id: UUID
    reason: str | None
    override_used: bool
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    safe_failure_code: str | None
    safe_failure_message: str | None
    comparison: CandidateComparison | None
    created_at: datetime
    updated_at: datetime
    monitoring_evaluation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RetrainingAuditRecord:
    """Append-only snapshot for every allowed or blocked evaluation."""

    id: UUID
    decision: RetrainingDecision
    policy_id: UUID
    evaluated_by_user_id: UUID
    evaluation_mode: RetrainingEvaluationMode
    override_used: bool
    override_reason: str | None
    created_request_id: UUID | None
    monitoring_evaluation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One task-aware metric comparison and its optimization direction."""

    metric: str
    source_value: float
    candidate_value: float
    higher_is_better: bool
    outcome: ComparisonStatus


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    """Advisory comparison that cannot mutate registry aliases."""

    status: ComparisonStatus
    metrics: tuple[MetricComparison, ...]
    source_model_version: str
    candidate_model_version: str
    compared_at: datetime


def retraining_idempotency_key(
    *,
    registered_model_name: str,
    source_model_version: str,
    trigger: RetrainingTrigger,
    policy_version: str,
) -> str:
    """Hash the exact effective trigger scope for replica-safe deduplication."""
    payload = {
        "model": registered_model_name,
        "policy_version": policy_version,
        "source_version": source_model_version,
        "trigger_reference": trigger.reference,
        "trigger_type": trigger.trigger_type.value,
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Retraining timestamps must include a UTC offset.")
    return value.astimezone(UTC)

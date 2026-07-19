"""Immutable model-promotion contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from app.ml.base import TrainerKey
from app.ml.promotion.exceptions import PromotionValidationError


class ModelAlias(StrEnum):
    """Platform-owned fitted-model aliases."""

    CANDIDATE = "candidate"
    CHALLENGER = "challenger"
    CHAMPION = "champion"


class PromotionAction(StrEnum):
    """Bounded governance mutation recorded by this milestone."""

    ASSIGN_ALIAS = "assign_alias"


class PromotionDecision(StrEnum):
    """Policy decision recorded for a promotion attempt."""

    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"


class PromotionOperationOutcome(StrEnum):
    """External alias operation state recorded in the audit log."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    """Version identity and evaluation-set metrics used by policy."""

    registered_model_name: str
    version: str
    key: TrainerKey
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


@dataclass(frozen=True, slots=True)
class PromotionEvaluation:
    """Serializable recommendation returned by a task-specific policy."""

    accepted: bool
    reason: str
    primary_metric: str
    candidate_value: float | None
    incumbent_value: float | None
    improvement: float | None
    safeguards: Mapping[str, bool]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "safeguards",
            MappingProxyType(dict(self.safeguards)),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the bounded JSON audit representation."""
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "primary_metric": self.primary_metric,
            "candidate_value": self.candidate_value,
            "incumbent_value": self.incumbent_value,
            "improvement": self.improvement,
            "safeguards": dict(self.safeguards),
        }


@dataclass(frozen=True, slots=True)
class ModelPromotionRequest:
    """Authorized request to assign a governed model alias."""

    registered_model_name: str
    version: str
    target_alias: ModelAlias
    requested_by_user_id: UUID
    force: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        """Normalize optional governance justification before authorization/audit."""
        if self.reason is None:
            return
        normalized = self.reason.strip()
        if len(normalized) > 2000:
            raise PromotionValidationError(
                "Promotion reasons must be at most 2000 characters.",
            )
        object.__setattr__(self, "reason", normalized or None)


@dataclass(frozen=True, slots=True)
class ModelPromotionAuditRecord:
    """Repository-owned snapshot of one promotion attempt."""

    id: UUID
    registered_model_name: str
    model_version: str
    key: TrainerKey
    target_alias: ModelAlias
    previous_version: str | None
    requested_by_user_id: UUID
    action: PromotionAction
    decision: PromotionDecision
    policy_result: Mapping[str, object]
    force: bool
    reason: str | None
    operation_outcome: PromotionOperationOutcome
    created_at: datetime
    completed_at: datetime | None
    error_code: str | None
    safe_error_message: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_result",
            MappingProxyType(dict(self.policy_result)),
        )


@dataclass(frozen=True, slots=True)
class ModelPromotionResult:
    """Completed governed alias assignment."""

    audit_id: UUID
    registered_model_name: str
    selected_version: str
    target_alias: ModelAlias
    previous_version: str | None
    evaluation: PromotionEvaluation
    overridden: bool
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class PromotionAuditReconciliationResult:
    """Stable IDs grouped by the observed reconciliation outcome."""

    succeeded: tuple[UUID, ...]
    conflicted: tuple[UUID, ...]
    registry_unavailable: tuple[UUID, ...]

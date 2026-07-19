"""Pure, deterministic retraining policy evaluation with no infrastructure imports."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.ml.monitoring import DriftSeverity
from app.ml.retraining.models import (
    CooldownState,
    QuotaState,
    RetrainingDecision,
    RetrainingDecisionStatus,
    RetrainingEvaluationMode,
    RetrainingPolicy,
    RetrainingTrigger,
)

_SEVERITY_ORDER = {
    DriftSeverity.INSUFFICIENT_DATA: 0,
    DriftSeverity.STABLE: 1,
    DriftSeverity.WARNING: 2,
    DriftSeverity.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class RetrainingEvaluationContext:
    """Already-resolved facts consumed by the side-effect-free evaluator."""

    policy: RetrainingPolicy
    registered_model_name: str
    source_model_version: str | None
    requested_alias: str | None
    trigger: RetrainingTrigger
    mode: RetrainingEvaluationMode
    source_is_champion: bool
    reference_profile_available: bool
    training_evidence_available: bool
    existing_equivalent_request_id: UUID | None
    active_request_id: UUID | None
    cooldown: CooldownState
    quota: QuotaState
    evaluated_at: datetime
    override_cooldown: bool = False


class RetrainingPolicyEvaluator:
    """Apply the documented policy checks in a stable first-failure order."""

    def evaluate(self, context: RetrainingEvaluationContext) -> RetrainingDecision:
        policy = context.policy
        trigger = context.trigger
        if not policy.enabled:
            return _decision(
                context, RetrainingDecisionStatus.DISABLED, "Policy disabled."
            )
        if trigger.trigger_type not in policy.allowed_trigger_types:
            return _decision(
                context,
                RetrainingDecisionStatus.NOT_ELIGIBLE,
                "Trigger type is not allowed by policy.",
            )
        if context.source_model_version is None:
            return _decision(
                context,
                RetrainingDecisionStatus.NOT_ELIGIBLE,
                "An exact source model version was not resolved.",
            )
        if policy.require_champion_source and not context.source_is_champion:
            return _decision(
                context,
                RetrainingDecisionStatus.NOT_ELIGIBLE,
                "The exact source version is not the current champion.",
            )
        if (
            context.mode is RetrainingEvaluationMode.AUTOMATIC
            and not context.reference_profile_available
        ):
            return _decision(
                context,
                RetrainingDecisionStatus.BLOCKED_MISSING_PROFILE,
                "The exact source version has no reference profile.",
            )
        if context.mode is RetrainingEvaluationMode.AUTOMATIC:
            if (
                trigger.aggregate_status is DriftSeverity.INSUFFICIENT_DATA
                or trigger.current_sample_count < policy.minimum_current_sample_count
            ):
                return _decision(
                    context,
                    RetrainingDecisionStatus.BLOCKED_INSUFFICIENT_DATA,
                    "The analyzed monitoring sample is insufficient.",
                )
            if trigger.truncated and not policy.allow_truncated_drift:
                return _decision(
                    context,
                    RetrainingDecisionStatus.BLOCKED_INSUFFICIENT_DATA,
                    "Policy does not allow truncated drift windows.",
                )
            severity = trigger.aggregate_status
            if (
                severity is None
                or _SEVERITY_ORDER[severity]
                < _SEVERITY_ORDER[policy.minimum_drift_status]
            ):
                return _decision(
                    context,
                    RetrainingDecisionStatus.NOT_ELIGIBLE,
                    "The drift threshold was not met.",
                )
        if not context.training_evidence_available:
            return _decision(
                context,
                RetrainingDecisionStatus.BLOCKED_MISSING_TRAINING_EVIDENCE,
                "Trusted source training evidence is unavailable.",
            )
        if context.existing_equivalent_request_id is not None:
            return _decision(
                context,
                RetrainingDecisionStatus.BLOCKED_DUPLICATE,
                "An equivalent retraining request already exists.",
                existing=context.existing_equivalent_request_id,
            )
        if context.active_request_id is not None:
            return _decision(
                context,
                RetrainingDecisionStatus.BLOCKED_QUOTA,
                "The exact model has reached its active-request limit.",
                existing=context.active_request_id,
            )
        if context.cooldown.active and not context.override_cooldown:
            return _decision(
                context,
                RetrainingDecisionStatus.BLOCKED_COOLDOWN,
                "The exact model is inside its accepted-request cooldown.",
            )
        if (
            context.mode is RetrainingEvaluationMode.AUTOMATIC
            and context.quota.requests_today >= context.quota.maximum_per_day
        ):
            return _decision(
                context,
                RetrainingDecisionStatus.BLOCKED_QUOTA,
                "The model has reached its daily retraining quota.",
            )
        if (
            context.mode is RetrainingEvaluationMode.AUTOMATIC
            and context.quota.requests_this_week >= context.quota.maximum_per_week
        ):
            return _decision(
                context,
                RetrainingDecisionStatus.BLOCKED_QUOTA,
                "The model has reached its weekly retraining quota.",
            )
        reasons = ["The retraining policy is eligible."]
        if trigger.truncated:
            reasons.append(
                trigger.analysis_warning or "The drift analysis window was truncated."
            )
        return _decision(
            context,
            RetrainingDecisionStatus.ELIGIBLE,
            *reasons,
        )


def _decision(
    context: RetrainingEvaluationContext,
    status: RetrainingDecisionStatus,
    *reasons: str,
    existing: UUID | None = None,
) -> RetrainingDecision:
    return RetrainingDecision(
        registered_model_name=context.registered_model_name,
        source_model_version=context.source_model_version,
        requested_alias=context.requested_alias,
        trigger=context.trigger,
        status=status,
        reasons=tuple(reasons),
        evaluated_at=context.evaluated_at,
        cooldown=context.cooldown,
        quota=context.quota,
        existing_request_id=existing,
    )

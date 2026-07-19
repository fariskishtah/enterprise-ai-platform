"""Pure ordered retraining policy tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.ml.monitoring import DriftSeverity
from app.ml.retraining import (
    CooldownState,
    QuotaState,
    RetrainingDecisionStatus,
    RetrainingEvaluationContext,
    RetrainingEvaluationMode,
    RetrainingPolicy,
    RetrainingPolicyEvaluator,
    RetrainingTrigger,
    RetrainingTriggerType,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)
POLICY_ID = UUID("00000000-0000-0000-0000-000000000101")
USER_ID = UUID("00000000-0000-0000-0000-000000000102")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000103")


def policy() -> RetrainingPolicy:
    return RetrainingPolicy(
        id=POLICY_ID,
        registered_model_name="factory_quality",
        enabled=True,
        allowed_trigger_types=frozenset(RetrainingTriggerType),
        minimum_drift_status=DriftSeverity.CRITICAL,
        minimum_current_sample_count=20,
        cooldown_seconds=3600,
        maximum_requests_per_day=1,
        maximum_requests_per_week=3,
        maximum_active_requests=1,
        require_champion_source=True,
        allow_truncated_drift=True,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def context() -> RetrainingEvaluationContext:
    return RetrainingEvaluationContext(
        policy=policy(),
        registered_model_name="factory_quality",
        source_model_version="7",
        requested_alias="champion",
        trigger=RetrainingTrigger(
            trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
            reference="window:7:2026-07-17:2026-07-18",
            aggregate_status=DriftSeverity.CRITICAL,
            matched_event_count=25,
            analyzed_event_count=25,
            current_sample_count=25,
            truncated=False,
            analysis_warning=None,
            thresholds={"psi_critical": 0.25},
        ),
        mode=RetrainingEvaluationMode.AUTOMATIC,
        source_is_champion=True,
        reference_profile_available=True,
        training_evidence_available=True,
        existing_equivalent_request_id=None,
        active_request_id=None,
        cooldown=CooldownState(False, None, None, 0),
        quota=QuotaState(0, 0, 0, 1, 3, 1),
        evaluated_at=NOW,
    )


def evaluate(value: RetrainingEvaluationContext) -> RetrainingDecisionStatus:
    return RetrainingPolicyEvaluator().evaluate(value).status


def test_critical_drift_with_trusted_evidence_is_eligible() -> None:
    decision = RetrainingPolicyEvaluator().evaluate(context())

    assert decision.status is RetrainingDecisionStatus.ELIGIBLE
    assert decision.source_model_version == "7"
    assert decision.trigger.thresholds == {"psi_critical": 0.25}
    assert decision.eligible is True


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("disabled", RetrainingDecisionStatus.DISABLED),
        ("trigger", RetrainingDecisionStatus.NOT_ELIGIBLE),
        ("source", RetrainingDecisionStatus.NOT_ELIGIBLE),
        ("champion", RetrainingDecisionStatus.NOT_ELIGIBLE),
        ("profile", RetrainingDecisionStatus.BLOCKED_MISSING_PROFILE),
        ("samples", RetrainingDecisionStatus.BLOCKED_INSUFFICIENT_DATA),
        ("threshold", RetrainingDecisionStatus.NOT_ELIGIBLE),
        (
            "evidence",
            RetrainingDecisionStatus.BLOCKED_MISSING_TRAINING_EVIDENCE,
        ),
        ("duplicate", RetrainingDecisionStatus.BLOCKED_DUPLICATE),
        ("active", RetrainingDecisionStatus.BLOCKED_QUOTA),
        ("cooldown", RetrainingDecisionStatus.BLOCKED_COOLDOWN),
        ("daily", RetrainingDecisionStatus.BLOCKED_QUOTA),
        ("weekly", RetrainingDecisionStatus.BLOCKED_QUOTA),
    ],
)
def test_policy_first_failure_branches(
    case: str, expected: RetrainingDecisionStatus
) -> None:
    assert evaluate(_case(case)) is expected


def _case(case: str) -> RetrainingEvaluationContext:
    value = context()
    if case == "disabled":
        return replace(value, policy=replace(policy(), enabled=False))
    if case == "trigger":
        return replace(
            value,
            policy=replace(
                policy(),
                allowed_trigger_types=frozenset({RetrainingTriggerType.MANUAL}),
            ),
        )
    if case == "source":
        return replace(value, source_model_version=None)
    if case == "champion":
        return replace(value, source_is_champion=False)
    if case == "profile":
        return replace(value, reference_profile_available=False)
    if case == "samples":
        return replace(
            value,
            trigger=replace(
                value.trigger,
                current_sample_count=19,
                aggregate_status=DriftSeverity.INSUFFICIENT_DATA,
            ),
        )
    if case == "threshold":
        return replace(
            value,
            trigger=replace(value.trigger, aggregate_status=DriftSeverity.WARNING),
        )
    if case == "evidence":
        return replace(value, training_evidence_available=False)
    if case == "duplicate":
        return replace(value, existing_equivalent_request_id=REQUEST_ID)
    if case == "active":
        return replace(value, active_request_id=REQUEST_ID)
    if case == "cooldown":
        return replace(
            value,
            cooldown=CooldownState(True, NOW, NOW + timedelta(hours=1), 3600),
        )
    if case == "daily":
        return replace(value, quota=QuotaState(1, 1, 0, 1, 3, 1))
    if case == "weekly":
        return replace(value, quota=QuotaState(0, 3, 0, 1, 3, 1))
    raise AssertionError(f"Unknown test case: {case}")


def test_disabled_precedes_all_later_failures() -> None:
    value = replace(
        context(),
        policy=replace(policy(), enabled=False),
        source_model_version=None,
        reference_profile_available=False,
        training_evidence_available=False,
        existing_equivalent_request_id=REQUEST_ID,
    )

    assert evaluate(value) is RetrainingDecisionStatus.DISABLED


def test_truncated_window_is_allowed_with_auditable_warning_by_default() -> None:
    value = replace(
        context(),
        trigger=replace(
            context().trigger,
            truncated=True,
            analysis_warning="Newest matching events only.",
        ),
    )

    decision = RetrainingPolicyEvaluator().evaluate(value)

    assert decision.status is RetrainingDecisionStatus.ELIGIBLE
    assert "Newest matching events only." in decision.reasons


def test_policy_can_block_truncated_window() -> None:
    value = replace(
        context(),
        policy=replace(policy(), allow_truncated_drift=False),
        trigger=replace(context().trigger, truncated=True),
    )

    assert evaluate(value) is RetrainingDecisionStatus.BLOCKED_INSUFFICIENT_DATA


def test_warning_threshold_can_be_enabled_explicitly() -> None:
    value = replace(
        context(),
        policy=replace(policy(), minimum_drift_status=DriftSeverity.WARNING),
        trigger=replace(context().trigger, aggregate_status=DriftSeverity.WARNING),
    )

    assert evaluate(value) is RetrainingDecisionStatus.ELIGIBLE


def test_manual_mode_skips_drift_and_automatic_frequency_quotas() -> None:
    value = replace(
        context(),
        mode=RetrainingEvaluationMode.MANUAL,
        trigger=replace(
            context().trigger,
            trigger_type=RetrainingTriggerType.MANUAL,
            aggregate_status=None,
            current_sample_count=0,
        ),
        reference_profile_available=False,
        quota=QuotaState(1, 3, 0, 1, 3, 1),
    )

    assert evaluate(value) is RetrainingDecisionStatus.ELIGIBLE


def test_admin_cooldown_override_does_not_override_active_limit() -> None:
    value = replace(
        context(),
        override_cooldown=True,
        active_request_id=REQUEST_ID,
        cooldown=CooldownState(True, NOW, NOW + timedelta(hours=1), 3600),
    )

    assert evaluate(value) is RetrainingDecisionStatus.BLOCKED_QUOTA

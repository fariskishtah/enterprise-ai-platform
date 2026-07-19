"""Controlled retraining model, lineage, and comparison tests."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.ml.domain import TaskType
from app.ml.jobs import RandomForestRegressionJobSpec
from app.ml.monitoring import DriftSeverity
from app.ml.retraining import (
    ComparisonStatus,
    RetrainingPolicy,
    RetrainingTrigger,
    RetrainingTriggerType,
    build_retraining_specification,
    compare_candidates,
    retraining_idempotency_key,
)

NOW = datetime(2026, 7, 18, tzinfo=UTC)
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000201")
POLICY_ID = UUID("00000000-0000-0000-0000-000000000202")
SOURCE_JOB_ID = UUID("00000000-0000-0000-0000-000000000203")
USER_ID = UUID("00000000-0000-0000-0000-000000000204")


def _trigger() -> RetrainingTrigger:
    return RetrainingTrigger(
        RetrainingTriggerType.FEATURE_DRIFT,
        "window:3:start:end",
        DriftSeverity.CRITICAL,
        25,
        25,
        25,
        False,
        None,
        {"critical": 0.25},
    )


def _source_specification() -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,)),
        training_targets=(0.0, 1.0, 2.0),
        evaluation_features=((0.5,), (1.5,)),
        evaluation_targets=(0.5, 1.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        random_seed=11,
        experiment_name="Retraining",
        registered_model_name="factory_quality",
        tags={"purpose": "trusted-source", "retraining": "stale"},
    )


def test_idempotency_is_stable_and_scoped_to_policy_version() -> None:
    first = retraining_idempotency_key(
        registered_model_name="factory_quality",
        source_model_version="3",
        trigger=_trigger(),
        policy_version="2026-07-18T00:00:00+00:00",
    )
    repeated = retraining_idempotency_key(
        registered_model_name="factory_quality",
        source_model_version="3",
        trigger=_trigger(),
        policy_version="2026-07-18T00:00:00+00:00",
    )
    updated_policy = retraining_idempotency_key(
        registered_model_name="factory_quality",
        source_model_version="3",
        trigger=_trigger(),
        policy_version="2026-07-19T00:00:00+00:00",
    )

    assert first == repeated
    assert len(first) == 64
    assert updated_policy != first


def test_trigger_detaches_mutable_threshold_mapping() -> None:
    thresholds = {"critical": 0.25}
    trigger = RetrainingTrigger(
        RetrainingTriggerType.PREDICTION_DRIFT,
        "window:3:start:end",
        DriftSeverity.CRITICAL,
        25,
        25,
        25,
        False,
        None,
        thresholds,
    )
    thresholds["critical"] = 0.5

    assert trigger.thresholds["critical"] == 0.25
    with pytest.raises(TypeError):
        trigger.thresholds["critical"] = 0.75  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("cooldown_seconds", -1, "non-negative"),
        ("maximum_requests_per_day", 0, "positive"),
        ("minimum_current_sample_count", 0, "positive"),
        ("minimum_drift_status", DriftSeverity.STABLE, "warning or critical"),
    ],
)
def test_policy_rejects_invalid_limits(field: str, value: object, message: str) -> None:
    values: dict[str, object] = {
        "id": POLICY_ID,
        "registered_model_name": "factory_quality",
        "enabled": True,
        "allowed_trigger_types": frozenset(RetrainingTriggerType),
        "minimum_drift_status": DriftSeverity.CRITICAL,
        "minimum_current_sample_count": 20,
        "cooldown_seconds": 3600,
        "maximum_requests_per_day": 1,
        "maximum_requests_per_week": 3,
        "maximum_active_requests": 1,
        "require_champion_source": True,
        "allow_truncated_drift": True,
        "created_by_user_id": USER_ID,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        RetrainingPolicy(**values)  # type: ignore[arg-type]


def test_specification_builder_copies_source_and_sets_protected_lineage() -> None:
    source = _source_specification()

    derived = build_retraining_specification(
        source=source,
        request_id=REQUEST_ID,
        trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
        source_model_version="3",
        source_training_job_id=SOURCE_JOB_ID,
        policy_id=POLICY_ID,
    )

    assert derived is not source
    assert derived.training_features == source.training_features
    assert derived.training_targets == source.training_targets
    assert derived.tags["purpose"] == "trusted-source"
    assert derived.tags["retraining"] == "true"
    assert derived.tags["retraining_request_id"] == str(REQUEST_ID)
    assert derived.tags["source_model_version"] == "3"
    assert derived.tags["source_training_job_id"] == str(SOURCE_JOB_ID)
    assert source.tags["retraining"] == "stale"


@pytest.mark.parametrize(
    ("task", "source", "candidate", "expected"),
    [
        (
            TaskType.REGRESSION,
            {"rmse": 1.0, "mae": 0.8, "r2": 0.5},
            {"rmse": 0.8, "mae": 0.7, "r2": 0.6},
            ComparisonStatus.BETTER,
        ),
        (
            TaskType.REGRESSION,
            {"rmse": 1.0, "mae": 0.8, "r2": 0.5},
            {"rmse": 1.2, "mae": 0.9, "r2": 0.4},
            ComparisonStatus.WORSE,
        ),
        (
            TaskType.CLASSIFICATION,
            {"accuracy": 0.8, "f1_macro": 0.75},
            {"accuracy": 0.82, "f1_macro": 0.72},
            ComparisonStatus.MIXED,
        ),
        (
            TaskType.CLASSIFICATION,
            {"accuracy": 0.8},
            {"f1_macro": 0.9},
            ComparisonStatus.NOT_COMPARABLE,
        ),
    ],
)
def test_candidate_comparison_uses_task_aware_metric_direction(
    task: TaskType,
    source: dict[str, float],
    candidate: dict[str, float],
    expected: ComparisonStatus,
) -> None:
    result = compare_candidates(
        task_type=task,
        source_metrics=source,
        candidate_metrics=candidate,
        source_model_version="3",
        candidate_model_version="4",
        compared_at=NOW,
    )

    assert result.status is expected
    assert result.source_model_version == "3"
    assert result.candidate_model_version == "4"

"""Immutable retraining-spec construction from trusted persisted job evidence."""

from uuid import UUID

from app.ml.jobs import (
    RandomForestClassificationJobSpec,
    RandomForestRegressionJobSpec,
    TrainingJobSpec,
)
from app.ml.retraining.models import RetrainingTriggerType

PROTECTED_RETRAINING_TAGS = frozenset(
    {
        "retraining",
        "retraining_request_id",
        "retraining_trigger",
        "source_model_version",
        "source_training_job_id",
        "retraining_policy_id",
    }
)


def build_retraining_specification(
    *,
    source: TrainingJobSpec,
    request_id: UUID,
    trigger_type: RetrainingTriggerType,
    source_model_version: str,
    source_training_job_id: UUID,
    policy_id: UUID,
) -> TrainingJobSpec:
    """Copy a source specification and replace protected lineage tags."""
    tags = {
        key: value
        for key, value in source.tags.items()
        if key not in PROTECTED_RETRAINING_TAGS
    }
    tags.update(
        {
            "retraining": "true",
            "retraining_request_id": str(request_id),
            "retraining_trigger": trigger_type.value,
            "source_model_version": source_model_version,
            "source_training_job_id": str(source_training_job_id),
            "retraining_policy_id": str(policy_id),
        }
    )
    payload = source.payload()
    payload["tags"] = tags
    if isinstance(source, RandomForestRegressionJobSpec):
        return RandomForestRegressionJobSpec.model_validate(payload)
    if isinstance(source, RandomForestClassificationJobSpec):
        return RandomForestClassificationJobSpec.model_validate(payload)
    raise TypeError("Unsupported trusted training specification.")

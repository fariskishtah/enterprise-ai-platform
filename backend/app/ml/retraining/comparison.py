"""Pure task-aware candidate comparison using established metric directions."""

from collections.abc import Mapping
from datetime import datetime
from math import isfinite

from app.ml.domain import TaskType
from app.ml.retraining.models import (
    CandidateComparison,
    ComparisonStatus,
    MetricComparison,
)

_METRICS: dict[TaskType, tuple[tuple[str, bool], ...]] = {
    TaskType.REGRESSION: (("rmse", False), ("mae", False), ("r2", True)),
    TaskType.CLASSIFICATION: (("f1_macro", True), ("accuracy", True)),
}


def compare_candidates(
    *,
    task_type: TaskType,
    source_metrics: Mapping[str, float],
    candidate_metrics: Mapping[str, float],
    source_model_version: str,
    candidate_model_version: str,
    compared_at: datetime,
) -> CandidateComparison:
    """Return an advisory result; this function has no registry mutation boundary."""
    comparisons: list[MetricComparison] = []
    for name, higher_is_better in _METRICS[task_type]:
        source = source_metrics.get(name)
        candidate = candidate_metrics.get(name)
        if (
            source is None
            or candidate is None
            or not isfinite(source)
            or not isfinite(candidate)
        ):
            continue
        if candidate == source:
            outcome = ComparisonStatus.MIXED
        elif (candidate > source) is higher_is_better:
            outcome = ComparisonStatus.BETTER
        else:
            outcome = ComparisonStatus.WORSE
        comparisons.append(
            MetricComparison(name, source, candidate, higher_is_better, outcome)
        )
    directional = {item.outcome for item in comparisons}
    if not comparisons:
        status = ComparisonStatus.NOT_COMPARABLE
    elif directional == {ComparisonStatus.BETTER}:
        status = ComparisonStatus.BETTER
    elif directional == {ComparisonStatus.WORSE}:
        status = ComparisonStatus.WORSE
    else:
        status = ComparisonStatus.MIXED
    return CandidateComparison(
        status=status,
        metrics=tuple(comparisons),
        source_model_version=source_model_version,
        candidate_model_version=candidate_model_version,
        compared_at=compared_at,
    )

"""Pure deterministic AutoML champion ranking."""

from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from app.ml.automl.metrics import MetricDirection


@dataclass(frozen=True, slots=True)
class ChampionCandidate:
    trial_id: UUID
    trial_number: int
    primary_metric_value: float
    metric_standard_deviation: float


def rank_champions(
    candidates: tuple[ChampionCandidate, ...], direction: MetricDirection
) -> tuple[ChampionCandidate, ...]:
    """Rank metric, lower variance, trial number, then stable UUID."""
    finite = tuple(
        candidate
        for candidate in candidates
        if isfinite(candidate.primary_metric_value)
        and isfinite(candidate.metric_standard_deviation)
    )
    multiplier = -1.0 if direction is MetricDirection.MAXIMIZE else 1.0
    return tuple(
        sorted(
            finite,
            key=lambda candidate: (
                multiplier * candidate.primary_metric_value,
                candidate.metric_standard_deviation,
                candidate.trial_number,
                str(candidate.trial_id),
            ),
        )
    )


def select_champion(
    candidates: tuple[ChampionCandidate, ...], direction: MetricDirection
) -> ChampionCandidate | None:
    ranked = rank_champions(candidates, direction)
    return ranked[0] if ranked else None

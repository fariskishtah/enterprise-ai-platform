"""Pure task-specific evaluation policies for explicit model promotion."""

from abc import ABC, abstractmethod
from math import isfinite

from app.ml.promotion.models import PromotionCandidate, PromotionEvaluation


class BasePromotionPolicy(ABC):
    """Evaluate a candidate against an optional current alias holder."""

    @abstractmethod
    def evaluate(
        self,
        candidate: PromotionCandidate,
        incumbent: PromotionCandidate | None,
    ) -> PromotionEvaluation:
        """Return a recommendation without mutating registry state."""


class RegressionPromotionPolicy(BasePromotionPolicy):
    """Require finite RMSE/R² and configured regression safeguards."""

    def __init__(
        self,
        *,
        minimum_r2: float,
        minimum_relative_rmse_improvement: float,
    ) -> None:
        if not isfinite(minimum_r2):
            raise ValueError("minimum_r2 must be finite.")
        if not 0 <= minimum_relative_rmse_improvement <= 1:
            raise ValueError(
                "minimum_relative_rmse_improvement must be between 0 and 1.",
            )
        self._minimum_r2 = minimum_r2
        self._minimum_improvement = minimum_relative_rmse_improvement

    def evaluate(
        self,
        candidate: PromotionCandidate,
        incumbent: PromotionCandidate | None,
    ) -> PromotionEvaluation:
        """Use lower RMSE as primary and R² as a minimum safeguard."""
        candidate_rmse = _metric(candidate, "rmse")
        candidate_r2 = _metric(candidate, "r2")
        r2_passed = candidate_r2 is not None and candidate_r2 >= self._minimum_r2
        if candidate_rmse is None or candidate_rmse < 0 or not r2_passed:
            return PromotionEvaluation(
                accepted=False,
                reason=(
                    "Candidate regression metrics are missing, invalid, or below "
                    "the R² safeguard."
                ),
                primary_metric="rmse",
                candidate_value=candidate_rmse,
                incumbent_value=None,
                improvement=None,
                safeguards={"minimum_r2": r2_passed},
            )

        incumbent_rmse = _metric(incumbent, "rmse") if incumbent else None
        if incumbent is None:
            return PromotionEvaluation(
                accepted=True,
                reason=(
                    "Candidate satisfies regression safeguards and no incumbent "
                    "exists."
                ),
                primary_metric="rmse",
                candidate_value=candidate_rmse,
                incumbent_value=None,
                improvement=None,
                safeguards={"minimum_r2": True},
            )
        if incumbent_rmse is None or incumbent_rmse < 0:
            return PromotionEvaluation(
                accepted=False,
                reason="Incumbent regression metrics are missing or invalid.",
                primary_metric="rmse",
                candidate_value=candidate_rmse,
                incumbent_value=incumbent_rmse,
                improvement=None,
                safeguards={"minimum_r2": True},
            )

        improvement = (
            0.0
            if incumbent_rmse == 0 and candidate_rmse == 0
            else (
                -1.0
                if incumbent_rmse == 0
                else (incumbent_rmse - candidate_rmse) / incumbent_rmse
            )
        )
        accepted = improvement >= self._minimum_improvement
        return PromotionEvaluation(
            accepted=accepted,
            reason=(
                "Candidate satisfies the configured relative RMSE improvement."
                if accepted
                else (
                    "Candidate does not satisfy the configured relative RMSE "
                    "improvement."
                )
            ),
            primary_metric="rmse",
            candidate_value=candidate_rmse,
            incumbent_value=incumbent_rmse,
            improvement=improvement,
            safeguards={"minimum_r2": True},
        )


class ClassificationPromotionPolicy(BasePromotionPolicy):
    """Require finite macro-F1/accuracy and configured safeguards."""

    def __init__(
        self,
        *,
        minimum_accuracy: float,
        minimum_f1_improvement: float,
    ) -> None:
        if not 0 <= minimum_accuracy <= 1:
            raise ValueError("minimum_accuracy must be between 0 and 1.")
        if not 0 <= minimum_f1_improvement <= 1:
            raise ValueError("minimum_f1_improvement must be between 0 and 1.")
        self._minimum_accuracy = minimum_accuracy
        self._minimum_improvement = minimum_f1_improvement

    def evaluate(
        self,
        candidate: PromotionCandidate,
        incumbent: PromotionCandidate | None,
    ) -> PromotionEvaluation:
        """Use higher macro-F1 as primary and accuracy as a safeguard."""
        candidate_f1 = _bounded_metric(candidate, "f1_macro")
        candidate_accuracy = _bounded_metric(candidate, "accuracy")
        accuracy_passed = (
            candidate_accuracy is not None
            and candidate_accuracy >= self._minimum_accuracy
        )
        if candidate_f1 is None or not accuracy_passed:
            return PromotionEvaluation(
                accepted=False,
                reason=(
                    "Candidate classification metrics are missing, invalid, or "
                    "below the accuracy safeguard."
                ),
                primary_metric="f1_macro",
                candidate_value=candidate_f1,
                incumbent_value=None,
                improvement=None,
                safeguards={"minimum_accuracy": accuracy_passed},
            )
        incumbent_f1 = _bounded_metric(incumbent, "f1_macro") if incumbent else None
        if incumbent is None:
            return PromotionEvaluation(
                accepted=True,
                reason=(
                    "Candidate satisfies classification safeguards and no incumbent "
                    "exists."
                ),
                primary_metric="f1_macro",
                candidate_value=candidate_f1,
                incumbent_value=None,
                improvement=None,
                safeguards={"minimum_accuracy": True},
            )
        if incumbent_f1 is None:
            return PromotionEvaluation(
                accepted=False,
                reason="Incumbent classification metrics are missing or invalid.",
                primary_metric="f1_macro",
                candidate_value=candidate_f1,
                incumbent_value=None,
                improvement=None,
                safeguards={"minimum_accuracy": True},
            )
        improvement = candidate_f1 - incumbent_f1
        accepted = improvement >= self._minimum_improvement
        return PromotionEvaluation(
            accepted=accepted,
            reason=(
                "Candidate satisfies the configured macro-F1 improvement."
                if accepted
                else "Candidate does not satisfy the configured macro-F1 improvement."
            ),
            primary_metric="f1_macro",
            candidate_value=candidate_f1,
            incumbent_value=incumbent_f1,
            improvement=improvement,
            safeguards={"minimum_accuracy": True},
        )


def _metric(candidate: PromotionCandidate | None, name: str) -> float | None:
    if candidate is None:
        return None
    value = candidate.metrics.get(name)
    return value if value is not None and isfinite(value) else None


def _bounded_metric(
    candidate: PromotionCandidate | None,
    name: str,
) -> float | None:
    value = _metric(candidate, name)
    return value if value is not None and 0 <= value <= 1 else None

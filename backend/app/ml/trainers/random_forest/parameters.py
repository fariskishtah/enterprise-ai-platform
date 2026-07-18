"""Typed parameters for the intentionally restricted Random Forest boundary.

The platform accepts only ``"sqrt"``, ``"log2"``, or fractional floats for
``max_features``; this is deliberately narrower than scikit-learn's full API.
"""

from typing import Annotated, Literal, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)

type RegressionCriterion = Literal[
    "squared_error",
    "absolute_error",
    "friedman_mse",
    "poisson",
]
type ClassificationCriterion = Literal["gini", "entropy", "log_loss"]
type MaxFeatures = Literal["sqrt", "log2"] | Annotated[
    float,
    Field(strict=True, gt=0, le=1),
]

PositiveStrictInt = Annotated[int, Field(strict=True, gt=0)]
SplitStrictInt = Annotated[int, Field(strict=True, ge=2)]


class _CommonRandomForestKwargs(TypedDict):
    n_estimators: int
    max_depth: int | None
    min_samples_split: int
    min_samples_leaf: int
    max_features: MaxFeatures
    bootstrap: bool
    n_jobs: int | None
    random_state: int | None


class RandomForestRegressionKwargs(_CommonRandomForestKwargs):
    """Keyword arguments accepted by the regression estimator boundary."""

    criterion: RegressionCriterion


class RandomForestClassificationKwargs(_CommonRandomForestKwargs):
    """Keyword arguments accepted by the classification estimator boundary."""

    criterion: ClassificationCriterion


class _RandomForestParameters(BaseModel):
    """Shared validated parameters for the initial Random Forest family."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    n_estimators: PositiveStrictInt = 100
    max_depth: PositiveStrictInt | None = None
    min_samples_split: SplitStrictInt = 2
    min_samples_leaf: PositiveStrictInt = 1
    max_features: MaxFeatures
    bootstrap: StrictBool = True
    n_jobs: StrictInt | None = None
    random_state: StrictInt | None = None

    @field_validator("max_features", mode="before")
    @classmethod
    def reject_integer_max_features(cls, value: object) -> object:
        """Keep integer counts outside the fractional platform boundary."""
        if isinstance(value, (bool, int)):
            raise ValueError(
                "max_features must be 'sqrt', 'log2', or a fractional float.",
            )
        return value

    @field_validator("n_jobs")
    @classmethod
    def reject_zero_n_jobs(cls, value: int | None) -> int | None:
        """Require non-zero worker counts when explicitly supplied."""
        if value == 0:
            msg = "n_jobs must be a non-zero integer or None."
            raise ValueError(msg)
        return value

    def _common_kwargs(self, *, random_seed: int | None) -> _CommonRandomForestKwargs:
        resolved_random_state = (
            random_seed if random_seed is not None else self.random_state
        )
        return {
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "min_samples_split": self.min_samples_split,
            "min_samples_leaf": self.min_samples_leaf,
            "max_features": self.max_features,
            "bootstrap": self.bootstrap,
            "n_jobs": self.n_jobs,
            "random_state": resolved_random_state,
        }


class RandomForestRegressionParameters(_RandomForestParameters):
    """Validated parameters accepted by Random Forest regression."""

    criterion: RegressionCriterion = "squared_error"
    max_features: MaxFeatures = 1.0

    def to_sklearn_kwargs(
        self,
        *,
        random_seed: int | None,
    ) -> RandomForestRegressionKwargs:
        """Return typed sklearn kwargs with workflow-seed precedence."""
        return {
            **self._common_kwargs(random_seed=random_seed),
            "criterion": self.criterion,
        }


class RandomForestClassificationParameters(_RandomForestParameters):
    """Validated parameters accepted by Random Forest classification."""

    criterion: ClassificationCriterion = "gini"
    max_features: MaxFeatures = "sqrt"

    def to_sklearn_kwargs(
        self,
        *,
        random_seed: int | None,
    ) -> RandomForestClassificationKwargs:
        """Return typed sklearn kwargs with workflow-seed precedence."""
        return {
            **self._common_kwargs(random_seed=random_seed),
            "criterion": self.criterion,
        }

"""Pydantic v2 transport schemas for synchronous AI Core APIs."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.ml.domain import AlgorithmType, TaskType
from app.ml.registry import RegisteredModelVersionStatus

PositiveStrictInt = Annotated[int, Field(strict=True, gt=0)]
SplitStrictInt = Annotated[int, Field(strict=True, ge=2)]
ApiMaxFeatures = (
    Literal["sqrt", "log2"]
    | Annotated[
        float,
        Field(strict=True, gt=0, le=1),
    ]
)
RegisteredModelName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,127}$"),
]
NonEmptyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
OptionalDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]


class _RandomForestHyperparameters(BaseModel):
    """Common typed Random Forest values accepted by the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_estimators: PositiveStrictInt = 100
    max_depth: PositiveStrictInt | None = None
    min_samples_split: SplitStrictInt = 2
    min_samples_leaf: PositiveStrictInt = 1
    max_features: ApiMaxFeatures
    bootstrap: StrictBool = True
    n_jobs: StrictInt | None = None
    random_state: StrictInt | None = None

    @field_validator("max_features", mode="before")
    @classmethod
    def reject_integer_max_features(cls, value: object) -> object:
        """Keep integer counts outside the fractional HTTP boundary."""
        if isinstance(value, (bool, int)):
            raise ValueError(
                "max_features must be 'sqrt', 'log2', or a fractional float.",
            )
        return value

    @field_validator("n_jobs")
    @classmethod
    def reject_zero_n_jobs(cls, value: int | None) -> int | None:
        """Match the intentional internal Random Forest parameter boundary."""
        if value == 0:
            raise ValueError("n_jobs must be a non-zero integer or None.")
        return value


class RandomForestRegressionHyperparameters(_RandomForestHyperparameters):
    """Typed Random Forest regression parameters accepted over HTTP."""

    criterion: Literal[
        "squared_error",
        "absolute_error",
        "friedman_mse",
        "poisson",
    ] = "squared_error"
    max_features: ApiMaxFeatures = 1.0


class RandomForestClassificationHyperparameters(_RandomForestHyperparameters):
    """Typed Random Forest classification parameters accepted over HTTP."""

    criterion: Literal["gini", "entropy", "log_loss"] = "gini"
    max_features: ApiMaxFeatures = "sqrt"


class _BaseTrainingRequest(BaseModel):
    """Transport values shared by regression and classification training."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    training_features: list[list[FiniteFloat]] = Field(min_length=1)
    evaluation_features: list[list[FiniteFloat]] = Field(min_length=1)
    random_seed: StrictInt | None = None
    experiment_name: NonEmptyName
    run_name: NonEmptyName | None = None
    registered_model_name: RegisteredModelName | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    model_description: OptionalDescription | None = None

    @field_validator("training_features", "evaluation_features", mode="before")
    @classmethod
    def reject_boolean_features(cls, value: object) -> object:
        """Reject booleans before Pydantic can coerce them to floats."""
        _reject_nested_booleans(value, name="features")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: dict[str, str]) -> dict[str, str]:
        """Require bounded non-empty tag keys and values."""
        for key, value in tags.items():
            if not key or len(key) > 250 or not value or len(value) > 5000:
                raise ValueError("tags require bounded non-empty keys and values.")
        return tags

    @model_validator(mode="after")
    def validate_feature_matrices(self) -> Self:
        """Reject ragged or empty-column matrices and incompatible widths."""
        training_width = _validate_rectangular_matrix(
            self.training_features,
            name="training_features",
        )
        evaluation_width = _validate_rectangular_matrix(
            self.evaluation_features,
            name="evaluation_features",
        )
        if training_width != evaluation_width:
            raise ValueError(
                "training and evaluation features must have equal column counts.",
            )
        return self


class RandomForestRegressionTrainingRequest(_BaseTrainingRequest):
    """Random Forest regression training transport request."""

    training_targets: list[FiniteFloat] = Field(min_length=1)
    evaluation_targets: list[FiniteFloat] = Field(min_length=1)
    hyperparameters: RandomForestRegressionHyperparameters = Field(
        default_factory=RandomForestRegressionHyperparameters,
    )

    @field_validator("training_targets", "evaluation_targets", mode="before")
    @classmethod
    def reject_boolean_targets(cls, value: object) -> object:
        """Reject booleans before regression float conversion."""
        _reject_flat_booleans(value, name="regression targets")
        return value

    @model_validator(mode="after")
    def validate_target_lengths(self) -> Self:
        """Require one regression target per feature row."""
        _validate_target_rows(
            self.training_features,
            self.training_targets,
            name="training",
        )
        _validate_target_rows(
            self.evaluation_features,
            self.evaluation_targets,
            name="evaluation",
        )
        return self


class RandomForestClassificationTrainingRequest(_BaseTrainingRequest):
    """Random Forest integer-label classification training request."""

    training_targets: list[StrictInt] = Field(min_length=1)
    evaluation_targets: list[StrictInt] = Field(min_length=1)
    hyperparameters: RandomForestClassificationHyperparameters = Field(
        default_factory=RandomForestClassificationHyperparameters,
    )

    @model_validator(mode="after")
    def validate_target_lengths(self) -> Self:
        """Require one classification label per feature row."""
        _validate_target_rows(
            self.training_features,
            self.training_targets,
            name="training",
        )
        _validate_target_rows(
            self.evaluation_features,
            self.evaluation_targets,
            name="evaluation",
        )
        return self


class RegisteredModelPredictionRequest(BaseModel):
    """Registered-model prediction transport request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registered_model_name: RegisteredModelName
    version_or_alias: Annotated[str, Field(min_length=1, max_length=128)]
    features: list[list[FiniteFloat]] = Field(min_length=1)

    @field_validator("features", mode="before")
    @classmethod
    def reject_boolean_features(cls, value: object) -> object:
        """Reject booleans before explicit float64 conversion."""
        _reject_nested_booleans(value, name="features")
        return value

    @model_validator(mode="after")
    def validate_feature_matrix(self) -> Self:
        """Reject ragged prediction matrices and empty columns."""
        _validate_rectangular_matrix(self.features, name="features")
        return self


class TrainerKeyResponse(BaseModel):
    """Transport representation of a composite trainer key."""

    model_config = ConfigDict(frozen=True)

    algorithm: AlgorithmType
    task_type: TaskType


class AITrainingResponse(BaseModel):
    """Safe response for a tracked and registered training execution."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    trainer_key: TrainerKeyResponse
    metrics: dict[str, float]
    mlflow_experiment_id: str
    mlflow_run_id: str
    mlflow_artifact_uri: str
    registered_model_name: str
    registered_model_version: str
    duration_seconds: float = Field(ge=0)


class RegisteredModelVersionResponse(BaseModel):
    """Safe transport metadata for a resolved registered model version."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    run_id: str
    trainer_key: TrainerKeyResponse
    status: RegisteredModelVersionStatus
    aliases: tuple[str, ...]


class RegressionPredictionResponse(BaseModel):
    """Random Forest regression prediction response."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    trainer_key: TrainerKeyResponse
    predictions: list[float]


class ClassificationPredictionResponse(BaseModel):
    """Random Forest classification prediction response."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    trainer_key: TrainerKeyResponse
    predictions: list[int]


def _validate_rectangular_matrix(
    matrix: list[list[float]],
    *,
    name: str,
) -> int:
    width = len(matrix[0])
    if width == 0:
        raise ValueError(f"{name} must contain at least one feature column.")
    if any(len(row) != width for row in matrix):
        raise ValueError(f"{name} must be rectangular.")
    return width


def _validate_target_rows(
    features: list[list[float]],
    targets: list[float] | list[int],
    *,
    name: str,
) -> None:
    if len(features) != len(targets):
        raise ValueError(f"{name} feature and target row counts must match.")


def _reject_nested_booleans(value: object, *, name: str) -> None:
    if isinstance(value, list):
        for row in value:
            if isinstance(row, list) and any(isinstance(item, bool) for item in row):
                raise ValueError(f"{name} must not contain boolean values.")


def _reject_flat_booleans(value: object, *, name: str) -> None:
    if isinstance(value, list) and any(isinstance(item, bool) for item in value):
        raise ValueError(f"{name} must not contain boolean values.")

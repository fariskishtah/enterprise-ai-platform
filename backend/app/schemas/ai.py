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
from app.ml.training_limits import (
    MAX_EVALUATION_ROWS,
    MAX_MODEL_DESCRIPTION_LENGTH,
    MAX_TRAINING_ROWS,
    MAX_TRAINING_RUN_NAME_LENGTH,
    MAX_TRAINING_TAG_KEY_LENGTH,
    MAX_TRAINING_TAG_VALUE_LENGTH,
    MAX_TRAINING_TAGS,
    validate_training_matrix_limits,
)

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
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_TRAINING_RUN_NAME_LENGTH,
    ),
]
OptionalDescription = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_MODEL_DESCRIPTION_LENGTH,
    ),
]


class _RandomForestHyperparameters(BaseModel):
    """Common typed Random Forest values accepted by the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_estimators: PositiveStrictInt = Field(
        default=100,
        description="Number of decision trees in the fitted forest.",
        examples=[5],
    )
    max_depth: PositiveStrictInt | None = Field(
        default=None,
        description="Maximum tree depth, or null to allow unbounded growth.",
        examples=[8],
    )
    min_samples_split: SplitStrictInt = Field(
        default=2,
        description="Minimum samples required to split an internal tree node.",
        examples=[2],
    )
    min_samples_leaf: PositiveStrictInt = Field(
        default=1,
        description="Minimum samples required at each leaf node.",
        examples=[1],
    )
    max_features: ApiMaxFeatures = Field(
        description=(
            "Features considered per split: 'sqrt', 'log2', or a fractional "
            "float in (0, 1]. Integer feature counts are intentionally unsupported."
        ),
    )
    bootstrap: StrictBool = Field(
        default=True,
        description="Whether each tree is fitted from a bootstrap sample.",
    )
    n_jobs: StrictInt | None = Field(
        default=None,
        description=(
            "Parallel worker count passed to Random Forest; zero is invalid and "
            "null uses the estimator default."
        ),
        examples=[1],
    )
    random_state: StrictInt | None = Field(
        default=None,
        description=(
            "Estimator seed used only when the request-level random_seed is null."
        ),
        examples=[17],
    )

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
    ] = Field(
        default="squared_error",
        description="Function used to measure regression split quality.",
        examples=["squared_error"],
    )
    max_features: ApiMaxFeatures = Field(
        default=1.0,
        description=(
            "Features considered per split: 'sqrt', 'log2', or a fractional "
            "float in (0, 1]. Integer feature counts are intentionally unsupported."
        ),
        examples=[1.0],
    )


class RandomForestClassificationHyperparameters(_RandomForestHyperparameters):
    """Typed Random Forest classification parameters accepted over HTTP."""

    criterion: Literal["gini", "entropy", "log_loss"] = Field(
        default="gini",
        description="Function used to measure classification split quality.",
        examples=["gini"],
    )
    max_features: ApiMaxFeatures = Field(
        default="sqrt",
        description=(
            "Features considered per split: 'sqrt', 'log2', or a fractional "
            "float in (0, 1]. Integer feature counts are intentionally unsupported."
        ),
        examples=["sqrt"],
    )


class _BaseTrainingRequest(BaseModel):
    """Transport values shared by regression and classification training."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    training_features: list[list[FiniteFloat]] = Field(
        min_length=1,
        max_length=MAX_TRAINING_ROWS,
        description=(
            "Non-empty rectangular row-by-feature matrix. Finite JSON numbers are "
            "converted explicitly to a two-dimensional float64 NumPy array."
        ),
        examples=[[[0.0, 1.0], [1.0, 1.5], [2.0, 2.0], [3.0, 2.5]]],
    )
    evaluation_features: list[list[FiniteFloat]] = Field(
        min_length=1,
        max_length=MAX_EVALUATION_ROWS,
        description=(
            "Held-out rectangular feature matrix used only for evaluation metrics. "
            "It must have the same column count as training_features."
        ),
        examples=[[[0.5, 1.25], [2.5, 2.25]]],
    )
    random_seed: StrictInt | None = Field(
        default=None,
        description=(
            "Workflow seed for reproducible fitting. When present, it overrides "
            "hyperparameters.random_state."
        ),
        examples=[17],
    )
    experiment_name: NonEmptyName = Field(
        description="MLflow experiment name that groups the completed run.",
        examples=["AI Core Manual Demo"],
    )
    run_name: NonEmptyName | None = Field(
        default=None,
        description="Optional human-readable MLflow run name.",
        examples=["regression-demo"],
    )
    registered_model_name: RegisteredModelName | None = Field(
        default=None,
        description=(
            "Optional safe MLflow registered-model name. When omitted, the platform "
            "builds a deterministic name from its configured prefix and trainer key."
        ),
        examples=["ai_core_random_forest_regression"],
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        max_length=MAX_TRAINING_TAGS,
        description=(
            "Optional user MLflow tags. Keys and values must be non-empty and may "
            "not replace protected platform metadata."
        ),
        examples=[{"purpose": "manual-demo"}],
    )
    model_description: OptionalDescription | None = Field(
        default=None,
        description="Optional description stored with the registered model version.",
        examples=["Small Random Forest demonstration model"],
    )

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
            if (
                not key
                or len(key) > MAX_TRAINING_TAG_KEY_LENGTH
                or not value
                or len(value) > MAX_TRAINING_TAG_VALUE_LENGTH
            ):
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
        validate_training_matrix_limits(
            training_rows=len(self.training_features),
            evaluation_rows=len(self.evaluation_features),
            feature_columns=training_width,
        )
        return self


class RandomForestRegressionTrainingRequest(_BaseTrainingRequest):
    """Random Forest regression training transport request."""

    training_targets: list[FiniteFloat] = Field(
        min_length=1,
        max_length=MAX_TRAINING_ROWS,
        description=(
            "Finite numeric regression targets, one per training row, converted "
            "explicitly to a one-dimensional float64 NumPy array."
        ),
        examples=[[1.0, 2.0, 3.0, 4.0]],
    )
    evaluation_targets: list[FiniteFloat] = Field(
        min_length=1,
        max_length=MAX_EVALUATION_ROWS,
        description=(
            "Finite numeric expected values, one per evaluation row, used to "
            "calculate MAE, MSE, RMSE, and R²."
        ),
        examples=[[1.5, 3.5]],
    )
    hyperparameters: RandomForestRegressionHyperparameters = Field(
        default_factory=RandomForestRegressionHyperparameters,
        description="Validated Random Forest regression estimator parameters.",
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

    training_targets: list[StrictInt] = Field(
        min_length=1,
        max_length=MAX_TRAINING_ROWS,
        description=(
            "Strict integer class labels, one per training row, converted explicitly "
            "to a one-dimensional int64 NumPy array. Include at least two classes."
        ),
        examples=[[0, 0, 1, 1]],
    )
    evaluation_targets: list[StrictInt] = Field(
        min_length=1,
        max_length=MAX_EVALUATION_ROWS,
        description=(
            "Strict integer expected labels, one per evaluation row, used to "
            "calculate accuracy and macro-averaged precision, recall, and F1."
        ),
        examples=[[0, 1]],
    )
    hyperparameters: RandomForestClassificationHyperparameters = Field(
        default_factory=RandomForestClassificationHyperparameters,
        description="Validated Random Forest classification estimator parameters.",
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

    registered_model_name: RegisteredModelName = Field(
        description="Safe MLflow registered-model name to resolve.",
        examples=["ai_core_random_forest_regression"],
    )
    version_or_alias: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Exact positive model version or an existing MLflow registry alias."
            ),
            examples=["1"],
        ),
    ]
    features: list[list[FiniteFloat]] = Field(
        min_length=1,
        description=(
            "Non-empty rectangular prediction matrix. Finite JSON numbers are "
            "converted explicitly to a two-dimensional float64 NumPy array."
        ),
        examples=[[[0.75, 1.4], [2.75, 2.4]]],
    )

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

    algorithm: AlgorithmType = Field(
        description="Training algorithm family used by the fitted model.",
        examples=["random_forest"],
    )
    task_type: TaskType = Field(
        description="Prediction task implemented by the fitted model.",
        examples=["regression"],
    )


class AITrainingResponse(BaseModel):
    """Safe response for a tracked and registered training execution."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID = Field(
        description="Platform UUID for this local training execution.",
        examples=["3f9655cb-8778-45e9-81e8-4566286200fb"],
    )
    trainer_key: TrainerKeyResponse = Field(
        description="Composite algorithm and task identity used for training.",
    )
    metrics: dict[str, float] = Field(
        description="Evaluation metrics calculated from the held-out evaluation set.",
        examples=[
            {"mae": 0.25, "mse": 0.125, "rmse": 0.3536, "r2": 0.8},
            {
                "accuracy": 1.0,
                "precision_macro": 1.0,
                "recall_macro": 1.0,
                "f1_macro": 1.0,
            },
        ],
    )
    mlflow_experiment_id: str = Field(
        description="MLflow identifier for the resolved or created experiment.",
        examples=["782451629603419811"],
    )
    mlflow_run_id: str = Field(
        description="MLflow identifier for the completed FINISHED run.",
        examples=["90f6f915646f4f79bf5c9a55304d3891"],
    )
    mlflow_artifact_uri: str = Field(
        description=(
            "MLflow URI of the registered model/model.joblib artifact. This is an "
            "integration URI, not the local artifact-manager filesystem path."
        ),
    )
    registered_model_name: str = Field(
        description="Safe MLflow registered-model name created or reused.",
        examples=["ai_core_random_forest_regression"],
    )
    registered_model_version: str = Field(
        description="New immutable positive model-version number.",
        examples=["1"],
    )
    duration_seconds: float = Field(
        ge=0,
        description="Non-negative model fitting duration in seconds.",
        examples=[0.042],
    )


class RegisteredModelVersionResponse(BaseModel):
    """Safe transport metadata for a resolved registered model version."""

    model_config = ConfigDict(frozen=True)

    model_name: str = Field(
        description="Resolved MLflow registered-model name.",
        examples=["ai_core_random_forest_regression"],
    )
    model_version: str = Field(
        description="Resolved immutable positive model-version number.",
        examples=["1"],
    )
    run_id: str = Field(
        description="MLflow source run associated with the registered artifact.",
        examples=["90f6f915646f4f79bf5c9a55304d3891"],
    )
    trainer_key: TrainerKeyResponse = Field(
        description="Protected algorithm and task metadata stored on the version.",
    )
    status: RegisteredModelVersionStatus = Field(
        description="Current MLflow model-version registration status.",
        examples=["READY"],
    )
    aliases: tuple[str, ...] = Field(
        description="Existing aliases currently assigned to the resolved version.",
        examples=[["champion"]],
    )


class RegressionPredictionResponse(BaseModel):
    """Random Forest regression prediction response."""

    model_config = ConfigDict(frozen=True)

    model_name: str = Field(
        description="Registered model used for prediction.",
        examples=["ai_core_random_forest_regression"],
    )
    model_version: str = Field(
        description="Exact resolved model version, including when an alias was used.",
        examples=["1"],
    )
    trainer_key: TrainerKeyResponse = Field(
        description="Validated regression trainer identity stored on the version.",
    )
    predictions: list[float] = Field(
        description="One float prediction for each supplied feature row.",
        examples=[[1.25, 3.5]],
    )


class ClassificationPredictionResponse(BaseModel):
    """Random Forest classification prediction response."""

    model_config = ConfigDict(frozen=True)

    model_name: str = Field(
        description="Registered model used for prediction.",
        examples=["ai_core_random_forest_classification"],
    )
    model_version: str = Field(
        description="Exact resolved model version, including when an alias was used.",
        examples=["1"],
    )
    trainer_key: TrainerKeyResponse = Field(
        description="Validated classification trainer identity stored on the version.",
    )
    predictions: list[int] = Field(
        description="One integer class label for each supplied feature row.",
        examples=[[0, 1]],
    )


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

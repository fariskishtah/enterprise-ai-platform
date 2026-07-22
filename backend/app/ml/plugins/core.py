"""Allowlisted model plugins and shared sklearn pipeline training."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import numpy as np
import numpy.typing as npt
from sklearn.base import BaseEstimator  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from app.ml.automl.search_space import PluginAutoMLSearchSpace

    class _BaseCalibratedSVC:
        cv: int

        def __init__(
            self,
            estimator: BaseEstimator | None = None,
            *,
            method: str = "sigmoid",
            cv: int | None = None,
            ensemble: bool = True,
        ) -> None: ...
        def fit(
            self,
            X: FeatureArray,
            y: TargetArray,
            sample_weight: TargetArray | None = None,
            **fit_params: object,
        ) -> BaseEstimator: ...

else:
    from sklearn.calibration import CalibratedClassifierCV as _BaseCalibratedSVC
from sklearn.ensemble import (  # type: ignore[import-untyped]
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import (  # type: ignore[import-untyped]
    ElasticNet,
    Lasso,
    LinearRegression,
    LogisticRegression,
    Ridge,
)
from sklearn.metrics import (  # type: ignore[import-untyped]
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.neighbors import (  # type: ignore[import-untyped]
    KNeighborsClassifier,
    KNeighborsRegressor,
)
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import (  # type: ignore[import-untyped]
    MinMaxScaler,
    RobustScaler,
    StandardScaler,
)
from sklearn.svm import SVC, SVR  # type: ignore[import-untyped]
from sklearn.tree import (  # type: ignore[import-untyped]
    DecisionTreeClassifier,
    DecisionTreeRegressor,
)

from app.ml.base import BaseTrainer, TrainerInput, TrainerKey, TrainerOutput
from app.ml.domain import AlgorithmType, TaskType
from app.ml.metrics import BaseMetricsEngine

FeatureArray = npt.NDArray[np.float64]
TargetArray = npt.NDArray[np.float64] | npt.NDArray[np.int64]
PredictionArray = npt.NDArray[np.float64] | npt.NDArray[np.int64]
ParameterKind = Literal["integer", "number", "boolean", "choice"]
ScalerChoice = Literal["auto", "none", "standard", "minmax", "robust"]
ImputerChoice = Literal["none", "mean", "median", "most_frequent"]


class ModelPluginError(ValueError):
    """Safe validation failure at the allowlisted plugin boundary."""


class DuplicateModelPluginError(ModelPluginError):
    """Raised when a public plugin identifier or trainer key is duplicated."""


class UnknownModelPluginError(ModelPluginError):
    """Raised when a request references an unregistered plugin."""


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """One allowlisted estimator setting exposed through discovery."""

    name: str
    kind: ParameterKind
    default: int | float | bool | str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    description: str = ""

    def validate(self, value: object) -> int | float | bool | str:
        """Return a normalized scalar or raise a client-safe error."""
        if self.kind == "boolean":
            if not isinstance(value, bool):
                raise ModelPluginError(f"{self.name} must be a boolean.")
            return value
        if self.kind == "choice":
            if not isinstance(value, str) or value not in self.choices:
                raise ModelPluginError(
                    f"{self.name} must be one of: {', '.join(self.choices)}."
                )
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ModelPluginError(f"{self.name} must be numeric.")
        normalized: int | float
        if self.kind == "integer":
            if not isinstance(value, int):
                raise ModelPluginError(f"{self.name} must be an integer.")
            normalized = value
        else:
            normalized = float(value)
            if not isfinite(normalized):
                raise ModelPluginError(f"{self.name} must be finite.")
        if self.minimum is not None and normalized < self.minimum:
            raise ModelPluginError(f"{self.name} must be at least {self.minimum}.")
        if self.maximum is not None and normalized > self.maximum:
            raise ModelPluginError(f"{self.name} must be at most {self.maximum}.")
        return normalized

    def public(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.kind,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": list(self.choices),
            "description": self.description,
        }


EstimatorFactory = Callable[[Mapping[str, object], int | None], BaseEstimator]


@dataclass(frozen=True, slots=True)
class ModelPlugin:
    """Complete safe construction and capability contract for one task."""

    id: str
    display_name: str
    description: str
    key: TrainerKey
    estimator_factory: EstimatorFactory
    parameters: tuple[ParameterDefinition, ...]
    default_scaler: ScalerChoice
    probability_support: bool = False
    decision_function_support: bool = False
    feature_importance_support: bool = False
    coefficient_support: bool = False
    permutation_importance_support: bool = True
    automl_search_space: PluginAutoMLSearchSpace | None = None

    def __post_init__(self) -> None:
        if self.automl_search_space is not None:
            self.validate_automl_search_space(self.automl_search_space)

    def validate_parameters(
        self, supplied: Mapping[str, object]
    ) -> Mapping[str, object]:
        definitions = {item.name: item for item in self.parameters}
        unknown = sorted(set(supplied) - set(definitions))
        if unknown:
            raise ModelPluginError(
                "Unsupported hyperparameters: " + ", ".join(unknown) + "."
            )
        values: dict[str, object] = {}
        for name, definition in definitions.items():
            values[name] = definition.validate(supplied.get(name, definition.default))
        return MappingProxyType(values)

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "algorithm_family": self.key.algorithm.value,
            "display_name": self.display_name,
            "description": self.description,
            "supported_tasks": [self.key.task_type.value],
            "parameters": [item.public() for item in self.parameters],
            "default_parameters": {item.name: item.default for item in self.parameters},
            "scaling_behavior": self.default_scaler,
            "probability_support": self.probability_support,
            "decision_function_support": self.decision_function_support,
            "feature_importance_support": self.feature_importance_support,
            "coefficient_support": self.coefficient_support,
            "permutation_importance_support": self.permutation_importance_support,
            "global_explainability": True,
            "local_explainability": False,
            "dependency_available": True,
        }

    def validate_automl_search_space(
        self, search_space: PluginAutoMLSearchSpace
    ) -> None:
        """Require an AutoML space to narrow this plugin's public parameters."""
        from app.ml.automl.search_space import (
            FloatSearchParameter,
            IntegerSearchParameter,
        )

        if (
            search_space.plugin_id != self.id
            or search_space.task_type is not self.key.task_type
        ):
            raise ModelPluginError("The AutoML search space does not match the plugin.")
        definitions = {definition.name: definition for definition in self.parameters}
        for parameter in search_space.parameters:
            definition = definitions.get(parameter.name)
            if definition is None:
                raise ModelPluginError(
                    "The AutoML search space contains an unknown parameter."
                )
            if isinstance(parameter, IntegerSearchParameter):
                if definition.kind != "integer":
                    raise ModelPluginError("The AutoML parameter kind is incompatible.")
                definition.validate(parameter.low)
                definition.validate(parameter.high)
                definition.validate(parameter.default)
            elif isinstance(parameter, FloatSearchParameter):
                if definition.kind != "number":
                    raise ModelPluginError("The AutoML parameter kind is incompatible.")
                definition.validate(parameter.low)
                definition.validate(parameter.high)
                definition.validate(parameter.default)
            else:
                expected = (
                    "boolean" if isinstance(parameter.default, bool) else "choice"
                )
                if definition.kind != expected:
                    raise ModelPluginError("The AutoML parameter kind is incompatible.")
                for choice in parameter.choices:
                    definition.validate(choice)
                definition.validate(parameter.default)


class ModelPluginRegistry:
    """Central allowlist for safe model construction and discovery."""

    def __init__(self) -> None:
        self._plugins: dict[str, ModelPlugin] = {}
        self._keys: dict[TrainerKey, ModelPlugin] = {}

    def register(self, plugin: ModelPlugin) -> None:
        if plugin.id in self._plugins or plugin.key in self._keys:
            raise DuplicateModelPluginError(
                f"A model plugin is already registered for '{plugin.id}'."
            )
        self._plugins[plugin.id] = plugin
        self._keys[plugin.key] = plugin

    def get(self, plugin_id: str, task_type: TaskType | None = None) -> ModelPlugin:
        try:
            plugin = self._plugins[plugin_id]
        except KeyError as exc:
            raise UnknownModelPluginError(
                "The requested algorithm is not available."
            ) from exc
        if task_type is not None and plugin.key.task_type is not task_type:
            raise ModelPluginError("The selected algorithm does not support this task.")
        return plugin

    def get_by_key(self, key: TrainerKey) -> ModelPlugin:
        try:
            return self._keys[key]
        except KeyError as exc:
            raise UnknownModelPluginError(
                "The model algorithm is not available."
            ) from exc

    def all(self) -> tuple[ModelPlugin, ...]:
        return tuple(sorted(self._plugins.values(), key=lambda item: item.id))


@dataclass(frozen=True, slots=True)
class PreprocessingOptions:
    scaler: ScalerChoice = "auto"
    imputer: ImputerChoice = "none"


class PluginTrainer(BaseTrainer[FeatureArray, TargetArray, Pipeline, PredictionArray]):
    """Fit one allowlisted estimator together with reusable preprocessing."""

    def __init__(self, plugin: ModelPlugin) -> None:
        self.plugin = plugin

    @property
    def key(self) -> TrainerKey:
        return self.plugin.key

    def fit(
        self, trainer_input: TrainerInput[FeatureArray, TargetArray]
    ) -> TrainerOutput[Pipeline]:
        supplied = dict(trainer_input.hyperparameters)
        preprocessing = PreprocessingOptions(
            scaler=_scaler_choice(supplied.pop("__scaler", "auto")),
            imputer=_imputer_choice(supplied.pop("__imputer", "none")),
        )
        parameters = self.plugin.validate_parameters(supplied)
        steps: list[tuple[str, object]] = []
        if preprocessing.imputer != "none":
            steps.append(
                (
                    "imputer",
                    SimpleImputer(strategy=preprocessing.imputer),
                )
            )
        scaler = _scaler(
            self.plugin.default_scaler
            if preprocessing.scaler == "auto"
            else preprocessing.scaler
        )
        if scaler is not None:
            steps.append(("scaler", scaler))
        steps.append(
            (
                "estimator",
                self.plugin.estimator_factory(parameters, trainer_input.random_seed),
            )
        )
        model = Pipeline(steps)
        started = perf_counter()
        model.fit(trainer_input.features, trainer_input.targets)
        return TrainerOutput(
            model=model,
            training_duration_seconds=perf_counter() - started,
        )

    def predict(self, model: Pipeline, features: FeatureArray) -> PredictionArray:
        predictions = np.asarray(model.predict(features))
        if self.key.task_type is TaskType.CLASSIFICATION:
            return predictions.astype(np.int64, copy=False)
        return predictions.astype(np.float64, copy=False)


@dataclass(frozen=True, slots=True)
class PluginMetricsReport:
    values: Mapping[str, float]

    def to_mapping(self) -> Mapping[str, float]:
        return MappingProxyType(dict(self.values))


class PluginMetricsEngine(
    BaseMetricsEngine[TargetArray, PredictionArray, PluginMetricsReport]
):
    def __init__(self, task_type: TaskType) -> None:
        self.task_type = task_type

    def evaluate(
        self, targets: TargetArray, predictions: PredictionArray
    ) -> PluginMetricsReport:
        if (
            targets.ndim != 1
            or predictions.ndim != 1
            or len(targets) != len(predictions)
        ):
            raise ModelPluginError(
                "Evaluation targets and predictions must be equal vectors."
            )
        if self.task_type is TaskType.CLASSIFICATION:
            values = {
                "accuracy": float(accuracy_score(targets, predictions)),
                "precision_macro": float(
                    precision_score(
                        targets, predictions, average="macro", zero_division=0
                    )
                ),
                "precision_weighted": float(
                    precision_score(
                        targets, predictions, average="weighted", zero_division=0
                    )
                ),
                "recall_macro": float(
                    recall_score(targets, predictions, average="macro", zero_division=0)
                ),
                "recall_weighted": float(
                    recall_score(
                        targets, predictions, average="weighted", zero_division=0
                    )
                ),
                "f1_macro": float(
                    f1_score(targets, predictions, average="macro", zero_division=0)
                ),
                "f1_weighted": float(
                    f1_score(targets, predictions, average="weighted", zero_division=0)
                ),
            }
        else:
            mse = float(mean_squared_error(targets, predictions))
            values = {
                "mae": float(mean_absolute_error(targets, predictions)),
                "mse": mse,
                "rmse": mse**0.5,
                "r2": float(r2_score(targets, predictions)),
                "median_absolute_error": float(
                    median_absolute_error(targets, predictions)
                ),
            }
            if not np.any(np.asarray(targets) == 0):
                values["mape"] = float(
                    mean_absolute_percentage_error(targets, predictions)
                )
        if not all(isfinite(value) for value in values.values()):
            raise ModelPluginError("Evaluation produced a non-finite metric.")
        return PluginMetricsReport(values)


def _scaler(choice: ScalerChoice) -> object | None:
    if choice in {"none", "auto"}:
        return None
    if choice == "standard":
        scaler: object = StandardScaler()
    elif choice == "minmax":
        scaler = MinMaxScaler()
    else:
        scaler = RobustScaler()
    return scaler


def _scaler_choice(value: object) -> ScalerChoice:
    if value not in {"auto", "none", "standard", "minmax", "robust"}:
        raise ModelPluginError("The preprocessing scaler is not available.")
    if value == "auto":
        return "auto"
    if value == "none":
        return "none"
    if value == "standard":
        return "standard"
    if value == "minmax":
        return "minmax"
    return "robust"


def _imputer_choice(value: object) -> ImputerChoice:
    if value not in {"none", "mean", "median", "most_frequent"}:
        raise ModelPluginError("The preprocessing imputer is not available.")
    if value == "mean":
        return "mean"
    if value == "median":
        return "median"
    if value == "most_frequent":
        return "most_frequent"
    return "none"


def _int(name: str, default: int, minimum: int, maximum: int) -> ParameterDefinition:
    return ParameterDefinition(name, "integer", default, minimum, maximum)


def _number(
    name: str, default: float, minimum: float, maximum: float
) -> ParameterDefinition:
    return ParameterDefinition(name, "number", default, minimum, maximum)


def _bool(name: str, default: bool) -> ParameterDefinition:
    return ParameterDefinition(name, "boolean", default)


def _choice(name: str, default: str, choices: tuple[str, ...]) -> ParameterDefinition:
    return ParameterDefinition(name, "choice", default, choices=choices)


def _seed(value: int | None) -> int:
    return 17 if value is None else value


class SafeCalibratedSVC(_BaseCalibratedSVC):
    """Dynamic calibration CV to prevent sklearn failures on small datasets."""

    def fit(
        self,
        X: FeatureArray,
        y: TargetArray,
        sample_weight: TargetArray | None = None,
        **fit_params: object,
    ) -> BaseEstimator:
        _, counts = np.unique(y, return_counts=True)
        min_count = int(np.min(counts))
        if min_count < 2:
            raise ModelPluginError(
                f"SVM probability calibration requires at least 2 samples per class. "
                f"Found minimum class count of {min_count}."
            )
        self.cv = min(5, min_count)
        return super().fit(X, y, sample_weight=sample_weight, **fit_params)


def create_default_plugin_registry() -> ModelPluginRegistry:
    """Build the dependency-free core sklearn catalog."""
    from app.ml.automl.search_space import (
        CategoricalSearchParameter,
        FloatSearchParameter,
        IntegerSearchParameter,
        PluginAutoMLSearchSpace,
        SearchParameter,
    )

    registry = ModelPluginRegistry()

    def add(
        plugin_id: str,
        display_name: str,
        description: str,
        algorithm: AlgorithmType,
        task: TaskType,
        factory: EstimatorFactory,
        parameters: tuple[ParameterDefinition, ...] = (),
        scaler: ScalerChoice = "none",
        automl_search_space: PluginAutoMLSearchSpace | None = None,
        **capabilities: bool,
    ) -> None:
        registry.register(
            ModelPlugin(
                plugin_id,
                display_name,
                description,
                TrainerKey(algorithm, task),
                factory,
                parameters,
                scaler,
                automl_search_space=automl_search_space,
                **capabilities,
            )
        )

    def space(
        plugin_id: str,
        task_type: TaskType,
        *parameters: SearchParameter,
        probability_support: bool = False,
    ) -> PluginAutoMLSearchSpace:
        return PluginAutoMLSearchSpace(
            plugin_id=plugin_id,
            task_type=task_type,
            parameters=parameters,
            probability_support=probability_support,
        )

    def integer(
        name: str, low: int, high: int, default: int, step: int = 1
    ) -> IntegerSearchParameter:
        return IntegerSearchParameter(
            name=name, low=low, high=high, default=default, step=step
        )

    def number(
        name: str,
        low: float,
        high: float,
        default: float,
        *,
        step: float | None = None,
        log_scale: bool = False,
    ) -> FloatSearchParameter:
        return FloatSearchParameter(
            name=name,
            low=low,
            high=high,
            default=default,
            step=step,
            log_scale=log_scale,
        )

    def categorical(
        name: str,
        choices: tuple[bool | str, ...],
        default: bool | str,
    ) -> CategoricalSearchParameter:
        return CategoricalSearchParameter(name=name, choices=choices, default=default)

    add(
        "logistic_regression",
        "Logistic Regression",
        "Regularized linear classifier.",
        AlgorithmType.LOGISTIC_REGRESSION,
        TaskType.CLASSIFICATION,
        lambda p, s: LogisticRegression(
            C=p["C"],
            max_iter=p["max_iter"],
            class_weight=None if p["class_weight"] == "none" else p["class_weight"],
            random_state=_seed(s),
        ),
        (
            _number("C", 1.0, 0.0001, 10000.0),
            _int("max_iter", 500, 50, 5000),
            _choice("class_weight", "none", ("none", "balanced")),
        ),
        "standard",
        automl_search_space=space(
            "logistic_regression",
            TaskType.CLASSIFICATION,
            number("C", 0.01, 100.0, 1.0, log_scale=True),
            categorical("class_weight", ("none", "balanced"), "none"),
            probability_support=True,
        ),
        probability_support=True,
        decision_function_support=True,
        coefficient_support=True,
    )
    add(
        "decision_tree_classification",
        "Decision Tree",
        "Bounded decision-tree classifier.",
        AlgorithmType.DECISION_TREE,
        TaskType.CLASSIFICATION,
        lambda p, s: DecisionTreeClassifier(
            max_depth=p["max_depth"],
            min_samples_leaf=p["min_samples_leaf"],
            random_state=_seed(s),
        ),
        (_int("max_depth", 8, 1, 64), _int("min_samples_leaf", 1, 1, 100)),
        automl_search_space=space(
            "decision_tree_classification",
            TaskType.CLASSIFICATION,
            integer("max_depth", 2, 32, 8, 2),
            integer("min_samples_leaf", 1, 10, 1),
            probability_support=True,
        ),
        probability_support=True,
        feature_importance_support=True,
    )
    add(
        "extra_trees_classification",
        "Extra Trees",
        "Randomized tree ensemble classifier.",
        AlgorithmType.EXTRA_TREES,
        TaskType.CLASSIFICATION,
        lambda p, s: ExtraTreesClassifier(
            n_estimators=p["n_estimators"],
            max_depth=p["max_depth"],
            min_samples_leaf=p["min_samples_leaf"],
            n_jobs=1,
            random_state=_seed(s),
        ),
        (
            _int("n_estimators", 100, 1, 500),
            _int("max_depth", 12, 1, 64),
            _int("min_samples_leaf", 1, 1, 100),
        ),
        automl_search_space=space(
            "extra_trees_classification",
            TaskType.CLASSIFICATION,
            integer("n_estimators", 50, 200, 100, 25),
            integer("max_depth", 4, 32, 12, 4),
            integer("min_samples_leaf", 1, 10, 1),
            probability_support=True,
        ),
        probability_support=True,
        feature_importance_support=True,
    )
    add(
        "knn_classification",
        "K-Nearest Neighbors",
        "Distance-based nearest-neighbor classifier.",
        AlgorithmType.KNN,
        TaskType.CLASSIFICATION,
        lambda p, _seed: KNeighborsClassifier(
            n_neighbors=p["n_neighbors"], weights=p["weights"], n_jobs=1
        ),
        (
            _int("n_neighbors", 5, 1, 100),
            _choice("weights", "uniform", ("uniform", "distance")),
        ),
        "standard",
        probability_support=True,
    )
    add(
        "svm_classification",
        "Support Vector Machine",
        "Kernel support-vector classifier with bounded probability output.",
        AlgorithmType.SVM,
        TaskType.CLASSIFICATION,
        lambda p, s: SafeCalibratedSVC(
            estimator=SVC(
                C=p["C"],
                kernel=p["kernel"],
                gamma=p["gamma"],
                max_iter=10_000,
                random_state=_seed(s),
            ),
            ensemble=False,
            cv=5,
        ),
        (
            _number("C", 1.0, 0.0001, 10000.0),
            _choice("kernel", "rbf", ("linear", "rbf", "poly", "sigmoid")),
            _choice("gamma", "scale", ("scale", "auto")),
        ),
        "standard",
        probability_support=True,
        decision_function_support=False,
        coefficient_support=False,
    )
    add(
        "gradient_boosting_classification",
        "Gradient Boosting",
        "Sequential boosted-tree classifier.",
        AlgorithmType.GRADIENT_BOOSTING,
        TaskType.CLASSIFICATION,
        lambda p, s: GradientBoostingClassifier(
            n_estimators=p["n_estimators"],
            learning_rate=p["learning_rate"],
            max_depth=p["max_depth"],
            random_state=_seed(s),
        ),
        (
            _int("n_estimators", 100, 1, 500),
            _number("learning_rate", 0.1, 0.001, 1.0),
            _int("max_depth", 3, 1, 16),
        ),
        automl_search_space=space(
            "gradient_boosting_classification",
            TaskType.CLASSIFICATION,
            integer("n_estimators", 50, 200, 100, 25),
            number("learning_rate", 0.01, 0.3, 0.1, log_scale=True),
            integer("max_depth", 1, 5, 3),
            probability_support=True,
        ),
        probability_support=True,
        feature_importance_support=True,
    )
    add(
        "random_forest_classification",
        "Random Forest",
        "Backward-compatible random-forest classifier.",
        AlgorithmType.RANDOM_FOREST,
        TaskType.CLASSIFICATION,
        lambda p, s: RandomForestClassifier(
            n_estimators=p["n_estimators"],
            max_depth=p["max_depth"],
            min_samples_leaf=p["min_samples_leaf"],
            n_jobs=1,
            random_state=_seed(s),
        ),
        (
            _int("n_estimators", 100, 1, 500),
            _int("max_depth", 12, 1, 64),
            _int("min_samples_leaf", 1, 1, 100),
        ),
        automl_search_space=space(
            "random_forest_classification",
            TaskType.CLASSIFICATION,
            integer("n_estimators", 50, 200, 100, 25),
            integer("max_depth", 4, 32, 12, 4),
            integer("min_samples_leaf", 1, 10, 1),
            probability_support=True,
        ),
        probability_support=True,
        feature_importance_support=True,
    )

    add(
        "linear_regression",
        "Linear Regression",
        "Ordinary least-squares regressor.",
        AlgorithmType.LINEAR_REGRESSION,
        TaskType.REGRESSION,
        lambda p, _seed: LinearRegression(fit_intercept=p["fit_intercept"], n_jobs=1),
        (_bool("fit_intercept", True),),
        coefficient_support=True,
    )
    add(
        "ridge_regression",
        "Ridge Regression",
        "L2-regularized linear regressor.",
        AlgorithmType.RIDGE,
        TaskType.REGRESSION,
        lambda p, s: Ridge(
            alpha=p["alpha"], fit_intercept=p["fit_intercept"], random_state=_seed(s)
        ),
        (_number("alpha", 1.0, 0.0, 10000.0), _bool("fit_intercept", True)),
        "standard",
        automl_search_space=space(
            "ridge_regression",
            TaskType.REGRESSION,
            number("alpha", 0.001, 100.0, 1.0, log_scale=True),
            categorical("fit_intercept", (True, False), True),
        ),
        coefficient_support=True,
    )
    add(
        "lasso_regression",
        "Lasso Regression",
        "L1-regularized linear regressor.",
        AlgorithmType.LASSO,
        TaskType.REGRESSION,
        lambda p, s: Lasso(
            alpha=p["alpha"],
            fit_intercept=p["fit_intercept"],
            max_iter=p["max_iter"],
            random_state=_seed(s),
        ),
        (
            _number("alpha", 0.1, 0.000001, 10000.0),
            _bool("fit_intercept", True),
            _int("max_iter", 2000, 100, 10000),
        ),
        "standard",
        automl_search_space=space(
            "lasso_regression",
            TaskType.REGRESSION,
            number("alpha", 0.0001, 10.0, 0.1, log_scale=True),
            categorical("fit_intercept", (True, False), True),
        ),
        coefficient_support=True,
    )
    add(
        "elastic_net_regression",
        "Elastic Net",
        "Combined L1/L2 regularized regressor.",
        AlgorithmType.ELASTIC_NET,
        TaskType.REGRESSION,
        lambda p, s: ElasticNet(
            alpha=p["alpha"],
            l1_ratio=p["l1_ratio"],
            fit_intercept=p["fit_intercept"],
            max_iter=p["max_iter"],
            random_state=_seed(s),
        ),
        (
            _number("alpha", 0.1, 0.000001, 10000.0),
            _number("l1_ratio", 0.5, 0.0, 1.0),
            _bool("fit_intercept", True),
            _int("max_iter", 2000, 100, 10000),
        ),
        "standard",
        automl_search_space=space(
            "elastic_net_regression",
            TaskType.REGRESSION,
            number("alpha", 0.0001, 10.0, 0.1, log_scale=True),
            number("l1_ratio", 0.1, 0.9, 0.5, step=0.1),
            categorical("fit_intercept", (True, False), True),
        ),
        coefficient_support=True,
    )
    add(
        "decision_tree_regression",
        "Decision Tree Regressor",
        "Bounded decision-tree regressor.",
        AlgorithmType.DECISION_TREE,
        TaskType.REGRESSION,
        lambda p, s: DecisionTreeRegressor(
            max_depth=p["max_depth"],
            min_samples_leaf=p["min_samples_leaf"],
            random_state=_seed(s),
        ),
        (_int("max_depth", 8, 1, 64), _int("min_samples_leaf", 1, 1, 100)),
        automl_search_space=space(
            "decision_tree_regression",
            TaskType.REGRESSION,
            integer("max_depth", 2, 32, 8, 2),
            integer("min_samples_leaf", 1, 10, 1),
        ),
        feature_importance_support=True,
    )
    add(
        "extra_trees_regression",
        "Extra Trees Regressor",
        "Randomized tree ensemble regressor.",
        AlgorithmType.EXTRA_TREES,
        TaskType.REGRESSION,
        lambda p, s: ExtraTreesRegressor(
            n_estimators=p["n_estimators"],
            max_depth=p["max_depth"],
            min_samples_leaf=p["min_samples_leaf"],
            n_jobs=1,
            random_state=_seed(s),
        ),
        (
            _int("n_estimators", 100, 1, 500),
            _int("max_depth", 12, 1, 64),
            _int("min_samples_leaf", 1, 1, 100),
        ),
        automl_search_space=space(
            "extra_trees_regression",
            TaskType.REGRESSION,
            integer("n_estimators", 50, 200, 100, 25),
            integer("max_depth", 4, 32, 12, 4),
            integer("min_samples_leaf", 1, 10, 1),
        ),
        feature_importance_support=True,
    )
    add(
        "knn_regression",
        "K-Nearest Neighbors Regressor",
        "Distance-based nearest-neighbor regressor.",
        AlgorithmType.KNN,
        TaskType.REGRESSION,
        lambda p, _seed: KNeighborsRegressor(
            n_neighbors=p["n_neighbors"], weights=p["weights"], n_jobs=1
        ),
        (
            _int("n_neighbors", 5, 1, 100),
            _choice("weights", "uniform", ("uniform", "distance")),
        ),
        "standard",
    )
    add(
        "svm_regression",
        "Support Vector Regressor",
        "Kernel support-vector regressor.",
        AlgorithmType.SVM,
        TaskType.REGRESSION,
        lambda p, _seed: SVR(
            C=p["C"], epsilon=p["epsilon"], kernel=p["kernel"], gamma=p["gamma"]
        ),
        (
            _number("C", 1.0, 0.0001, 10000.0),
            _number("epsilon", 0.1, 0.0, 1000.0),
            _choice("kernel", "rbf", ("linear", "rbf", "poly", "sigmoid")),
            _choice("gamma", "scale", ("scale", "auto")),
        ),
        "standard",
    )
    add(
        "gradient_boosting_regression",
        "Gradient Boosting Regressor",
        "Sequential boosted-tree regressor.",
        AlgorithmType.GRADIENT_BOOSTING,
        TaskType.REGRESSION,
        lambda p, s: GradientBoostingRegressor(
            n_estimators=p["n_estimators"],
            learning_rate=p["learning_rate"],
            max_depth=p["max_depth"],
            loss=p["loss"],
            random_state=_seed(s),
        ),
        (
            _int("n_estimators", 100, 1, 500),
            _number("learning_rate", 0.1, 0.001, 1.0),
            _int("max_depth", 3, 1, 16),
            _choice(
                "loss", "squared_error", ("squared_error", "absolute_error", "huber")
            ),
        ),
        automl_search_space=space(
            "gradient_boosting_regression",
            TaskType.REGRESSION,
            integer("n_estimators", 50, 200, 100, 25),
            number("learning_rate", 0.01, 0.3, 0.1, log_scale=True),
            integer("max_depth", 1, 5, 3),
            categorical(
                "loss",
                ("squared_error", "absolute_error", "huber"),
                "squared_error",
            ),
        ),
        feature_importance_support=True,
    )
    add(
        "random_forest_regression",
        "Random Forest Regressor",
        "Backward-compatible random-forest regressor.",
        AlgorithmType.RANDOM_FOREST,
        TaskType.REGRESSION,
        lambda p, s: RandomForestRegressor(
            n_estimators=p["n_estimators"],
            max_depth=p["max_depth"],
            min_samples_leaf=p["min_samples_leaf"],
            n_jobs=1,
            random_state=_seed(s),
        ),
        (
            _int("n_estimators", 100, 1, 500),
            _int("max_depth", 12, 1, 64),
            _int("min_samples_leaf", 1, 1, 100),
        ),
        automl_search_space=space(
            "random_forest_regression",
            TaskType.REGRESSION,
            integer("n_estimators", 50, 200, 100, 25),
            integer("max_depth", 4, 32, 12, 4),
            integer("min_samples_leaf", 1, 10, 1),
        ),
        feature_importance_support=True,
    )
    return registry

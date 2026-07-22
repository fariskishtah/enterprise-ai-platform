"""Leakage-safe deterministic cross-validation for allowlisted model plugins."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from statistics import fmean, pstdev

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt
from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]
from sklearn.model_selection import (  # type: ignore[import-untyped]
    KFold,
    StratifiedKFold,
)

from app.ml.automl.metrics import MetricDirection, require_automl_metric
from app.ml.base import TrainerInput
from app.ml.domain import TaskType
from app.ml.plugins import (
    PluginMetricsEngine,
    PluginTrainer,
    create_default_plugin_registry,
)

type JsonScalar = bool | int | float | str
type CancellationCheck = Callable[[], bool]


class CrossValidationRequest(BaseModel):
    """Bounded JSON-safe payload accepted by the child process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: TaskType
    plugin_id: str = Field(min_length=1, max_length=64)
    parameters: dict[str, JsonScalar] = Field(max_length=32)
    scaler: str = Field(pattern="^(auto|none|standard|minmax|robust)$")
    imputer: str = Field(pattern="^(none|mean|median|most_frequent)$")
    primary_metric: str = Field(min_length=1, max_length=64)
    metric_direction: MetricDirection
    random_seed: StrictInt
    folds: int = Field(ge=2, le=10)
    features: tuple[tuple[FiniteFloat, ...], ...] = Field(min_length=2)
    targets: tuple[StrictInt | FiniteFloat, ...] = Field(min_length=2)


class CrossValidationResult(BaseModel):
    """Finite fold metrics and aggregate mean/std values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fold_metrics: tuple[dict[str, FiniteFloat], ...]
    aggregate_metrics: dict[str, FiniteFloat]
    primary_metric_value: FiniteFloat


class CrossValidationCancelled(RuntimeError):
    pass


def execute_cross_validation(
    request: CrossValidationRequest,
    *,
    cancelled: CancellationCheck | None = None,
) -> CrossValidationResult:
    """Fit preprocessing and estimator independently inside every fold."""
    plugin = create_default_plugin_registry().get(request.plugin_id, request.task_type)
    metric = require_automl_metric(
        request.primary_metric,
        task_type=request.task_type,
        direction=request.metric_direction,
    )
    if metric.requires_probabilities and not plugin.probability_support:
        raise ValueError("The selected metric requires probability support.")
    features = np.asarray(request.features, dtype=np.float64)
    if features.ndim != 2 or not features.shape[1]:
        raise ValueError("Cross-validation requires a rectangular feature matrix.")
    target_dtype = (
        np.int64 if request.task_type is TaskType.CLASSIFICATION else np.float64
    )
    targets = np.asarray(request.targets, dtype=target_dtype)
    if targets.ndim != 1 or len(targets) != len(features):
        raise ValueError("Cross-validation features and targets must align.")
    if request.task_type is TaskType.CLASSIFICATION:
        _, counts = np.unique(targets, return_counts=True)
        if len(counts) < 2 or request.folds > int(counts.min()):
            raise ValueError("Cross-validation folds exceed the minimum class count.")
        splitter = StratifiedKFold(
            n_splits=request.folds, shuffle=True, random_state=request.random_seed
        )
        splits = splitter.split(features, targets)
    else:
        splitter = KFold(
            n_splits=request.folds, shuffle=True, random_state=request.random_seed
        )
        splits = splitter.split(features)
    fold_values: list[dict[str, float]] = []
    for fold_number, (training_indexes, validation_indexes) in enumerate(splits):
        if cancelled is not None and cancelled():
            raise CrossValidationCancelled("Cross-validation was cancelled.")
        trainer = PluginTrainer(plugin)
        hyperparameters: dict[str, object] = {
            **request.parameters,
            "__scaler": request.scaler,
            "__imputer": request.imputer,
        }
        output = trainer.fit(
            TrainerInput(
                features=features[training_indexes],
                targets=targets[training_indexes],
                hyperparameters=hyperparameters,
                random_seed=request.random_seed + fold_number,
            )
        )
        validation_features = features[validation_indexes]
        validation_targets = targets[validation_indexes]
        predictions = trainer.predict(output.model, validation_features)
        metric_values = dict(
            PluginMetricsEngine(request.task_type)
            .evaluate(validation_targets, predictions)
            .to_mapping()
        )
        if request.primary_metric == "roc_auc":
            probabilities = np.asarray(output.model.predict_proba(validation_features))
            labels = np.unique(targets)
            metric_values["roc_auc"] = float(
                roc_auc_score(
                    validation_targets,
                    probabilities[:, 1] if len(labels) == 2 else probabilities,
                    multi_class="ovr" if len(labels) > 2 else "raise",
                    average="weighted",
                    labels=labels,
                )
            )
        if request.primary_metric not in metric_values or not all(
            isfinite(value) for value in metric_values.values()
        ):
            raise ValueError("Cross-validation produced an unavailable metric.")
        fold_values.append(metric_values)
    aggregate: dict[str, float] = {}
    for key in sorted(set.intersection(*(set(item) for item in fold_values))):
        samples = [item[key] for item in fold_values]
        aggregate[f"{key}_mean"] = fmean(samples)
        aggregate[f"{key}_std"] = pstdev(samples)
    primary = aggregate[f"{request.primary_metric}_mean"]
    if not all(isfinite(value) for value in aggregate.values()):
        raise ValueError("Cross-validation aggregates must be finite.")
    return CrossValidationResult(
        fold_metrics=tuple(fold_values),
        aggregate_metrics=aggregate,
        primary_metric_value=primary,
    )

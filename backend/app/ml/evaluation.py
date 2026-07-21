"""Bounded, JSON-safe held-out evaluation and global explainability."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
from sklearn.calibration import calibration_curve  # type: ignore[import-untyped]
from sklearn.inspection import permutation_importance  # type: ignore[import-untyped]
from sklearn.metrics import (  # type: ignore[import-untyped]
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    precision_recall_curve,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]

from app.ml.domain import TaskType
from app.ml.plugins import ModelPlugin

MAX_CHART_POINTS = 200
MAX_EXPLANATION_FEATURES = 50
MAX_PERMUTATION_ROWS = 500


@runtime_checkable
class _Predictor(Protocol):
    def predict(self, features: object) -> object:
        """Return model predictions for a numeric matrix."""


def build_evaluation_payload(
    *,
    plugin: ModelPlugin,
    model: object,
    features: npt.NDArray[np.float64],
    targets: npt.NDArray[np.float64] | npt.NDArray[np.int64],
    feature_names: Sequence[str] | None = None,
    random_seed: int = 17,
) -> dict[str, object]:
    """Evaluate one fitted model on held-out data with bounded plot output."""
    if features.ndim != 2 or targets.ndim != 1 or len(features) != len(targets):
        raise ValueError(
            "Evaluation data must contain aligned matrix rows and targets."
        )
    if not len(features):
        raise ValueError("Evaluation data cannot be empty.")
    predictor = _predictor(model)
    predictions = np.asarray(predictor.predict(features))
    names = _feature_names(features.shape[1], feature_names)
    if plugin.key.task_type is TaskType.CLASSIFICATION:
        result = _classification_payload(
            plugin, predictor, features, targets, predictions
        )
    else:
        result = _regression_payload(targets, predictions)
    result["explainability"] = _explainability(
        plugin=plugin,
        model=predictor,
        features=features,
        targets=targets,
        feature_names=names,
        random_seed=random_seed,
    )
    result["schema_version"] = "1.0"
    result["task_type"] = plugin.key.task_type.value
    result["algorithm"] = plugin.id
    result["sample_count"] = len(features)
    result["feature_count"] = features.shape[1]
    safe_result = _json_safe(result)
    if not isinstance(safe_result, dict):
        raise ValueError("Evaluation serialization produced an invalid payload.")
    return {str(key): item for key, item in safe_result.items()}


def _classification_payload(
    plugin: ModelPlugin,
    model: object,
    features: npt.NDArray[np.float64],
    targets: npt.NDArray[np.float64] | npt.NDArray[np.int64],
    predictions: npt.NDArray[np.generic],
) -> dict[str, object]:
    labels = np.unique(np.concatenate((targets, predictions)))
    metrics: dict[str, float] = {
        "accuracy": float(accuracy_score(targets, predictions)),
        "precision_macro": float(
            precision_score(targets, predictions, average="macro", zero_division=0)
        ),
        "precision_weighted": float(
            precision_score(targets, predictions, average="weighted", zero_division=0)
        ),
        "recall_macro": float(
            recall_score(targets, predictions, average="macro", zero_division=0)
        ),
        "recall_weighted": float(
            recall_score(targets, predictions, average="weighted", zero_division=0)
        ),
        "f1_macro": float(
            f1_score(targets, predictions, average="macro", zero_division=0)
        ),
        "f1_weighted": float(
            f1_score(targets, predictions, average="weighted", zero_division=0)
        ),
    }
    omitted: dict[str, str] = {}
    plots: dict[str, object] = {
        "confusion_matrix": {
            "labels": [_label(value) for value in labels],
            "values": confusion_matrix(targets, predictions, labels=labels).tolist(),
        },
        "class_distribution": [
            {"label": _label(value), "count": int(np.sum(targets == value))}
            for value in labels
        ],
    }
    probabilities = None
    if plugin.probability_support and hasattr(model, "predict_proba"):
        probabilities = np.asarray(model.predict_proba(features), dtype=np.float64)
    if probabilities is None:
        omitted.update(
            {
                "roc_auc": "The estimator does not expose probabilities.",
                "log_loss": "The estimator does not expose probabilities.",
                "roc_curve": "The estimator does not expose probabilities.",
                "precision_recall_curve": (
                    "The estimator does not expose probabilities."
                ),
                "calibration": "The estimator does not expose probabilities.",
            }
        )
    else:
        try:
            metrics["log_loss"] = float(log_loss(targets, probabilities, labels=labels))
            if len(labels) == 2:
                positive = probabilities[:, 1]
                metrics["roc_auc"] = float(roc_auc_score(targets, positive))
                fpr, tpr, roc_thresholds = roc_curve(
                    targets, positive, pos_label=labels[1]
                )
                precision, recall, pr_thresholds = precision_recall_curve(
                    targets, positive, pos_label=labels[1]
                )
                plots["roc_curve"] = _xy(fpr, tpr, roc_thresholds)
                plots["precision_recall_curve"] = _xy(recall, precision, pr_thresholds)
                plots["probability_distribution"] = _histogram(positive)
                if len(targets) >= 10:
                    observed, predicted = calibration_curve(
                        targets == labels[1], positive, n_bins=min(10, len(targets))
                    )
                    plots["calibration"] = _pairs(predicted, observed)
                else:
                    omitted["calibration"] = (
                        "At least 10 held-out samples are required."
                    )
            else:
                metrics["roc_auc"] = float(
                    roc_auc_score(
                        targets,
                        probabilities,
                        multi_class="ovr",
                        average="weighted",
                        labels=labels,
                    )
                )
                omitted["roc_curve"] = (
                    "A single aggregate ROC curve is not emitted for multiclass models."
                )
                omitted["precision_recall_curve"] = (
                    "A single aggregate precision-recall curve is not emitted for "
                    "multiclass models."
                )
                omitted["calibration"] = (
                    "Multiclass calibration curves are not emitted."
                )
        except ValueError:
            omitted["probability_metrics"] = (
                "Held-out labels do not support probability metrics."
            )
    return {
        "metrics": metrics,
        "plots": plots,
        "classification_report": classification_report(
            targets, predictions, output_dict=True, zero_division=0
        ),
        "omitted": omitted,
    }


def _regression_payload(
    targets: npt.NDArray[np.float64] | npt.NDArray[np.int64],
    predictions: npt.NDArray[np.generic],
) -> dict[str, object]:
    expected = np.asarray(targets, dtype=np.float64)
    predicted = np.asarray(predictions, dtype=np.float64)
    residuals = expected - predicted
    errors = np.abs(residuals)
    mse = float(mean_squared_error(expected, predicted))
    metrics = {
        "mae": float(mean_absolute_error(expected, predicted)),
        "mse": mse,
        "rmse": mse**0.5,
        "r2": float(r2_score(expected, predicted)),
        "median_absolute_error": float(median_absolute_error(expected, predicted)),
    }
    omitted: dict[str, str] = {}
    if np.any(expected == 0):
        omitted["mape"] = "MAPE is omitted because held-out targets contain zero."
    else:
        metrics["mape"] = float(mean_absolute_percentage_error(expected, predicted))
    indexes = _sample_indexes(len(expected))
    return {
        "metrics": metrics,
        "plots": {
            "actual_vs_predicted": [
                {"actual": float(expected[i]), "predicted": float(predicted[i])}
                for i in indexes
            ],
            "residuals": [
                {"predicted": float(predicted[i]), "residual": float(residuals[i])}
                for i in indexes
            ],
            "residual_distribution": _histogram(residuals),
            "absolute_error_distribution": _histogram(errors),
            "error_by_prediction_range": _error_by_range(predicted, errors),
        },
        "omitted": omitted,
    }


def _explainability(
    *,
    plugin: ModelPlugin,
    model: object,
    features: npt.NDArray[np.float64],
    targets: npt.NDArray[np.generic],
    feature_names: list[str],
    random_seed: int,
) -> dict[str, object]:
    estimator = model.steps[-1][1] if isinstance(model, Pipeline) else model
    result: dict[str, object] = {
        "local": {
            "supported": False,
            "reason": (
                "Local contribution explanations are not available for this algorithm."
            ),
        },
        "notice": (
            "Model explanations describe model behavior and are not causal conclusions."
        ),
    }
    if plugin.feature_importance_support and hasattr(estimator, "feature_importances_"):
        result["native_feature_importance"] = _ranked(
            feature_names, np.asarray(estimator.feature_importances_)
        )
    else:
        result["native_feature_importance"] = {
            "supported": False,
            "reason": "Native feature importance is not available.",
        }
    if plugin.coefficient_support and hasattr(estimator, "coef_"):
        coefficients = np.asarray(estimator.coef_, dtype=np.float64)
        if coefficients.ndim > 1:
            coefficients = np.mean(np.abs(coefficients), axis=0)
        result["coefficients"] = _ranked(feature_names, coefficients)
    else:
        result["coefficients"] = {
            "supported": False,
            "reason": "Model coefficients are not available.",
        }
    try:
        limited = min(len(features), MAX_PERMUTATION_ROWS)
        importance = permutation_importance(
            model,
            features[:limited],
            targets[:limited],
            n_repeats=3,
            random_state=random_seed,
            n_jobs=1,
        )
        result["permutation_importance"] = _ranked(
            feature_names, np.asarray(importance.importances_mean)
        )
    except (TypeError, ValueError):
        result["permutation_importance"] = {
            "supported": False,
            "reason": (
                "Permutation importance could not be calculated for this "
                "held-out sample."
            ),
        }
    return result


def _predictor(model: object) -> _Predictor:
    if not isinstance(model, _Predictor):
        raise ValueError("The registered model does not support prediction.")
    return model


def _feature_names(width: int, names: Sequence[str] | None) -> list[str]:
    if names is not None and len(names) == width:
        return [str(name)[:128] for name in names]
    return [f"feature_{index}" for index in range(width)]


def _sample_indexes(size: int) -> npt.NDArray[np.int64]:
    if size <= MAX_CHART_POINTS:
        return np.arange(size, dtype=np.int64)
    return np.linspace(0, size - 1, MAX_CHART_POINTS, dtype=np.int64)


def _pairs(
    x: npt.NDArray[np.generic], y: npt.NDArray[np.generic]
) -> list[dict[str, float]]:
    indexes = _sample_indexes(len(x))
    return [{"x": float(x[i]), "y": float(y[i])} for i in indexes]


def _xy(
    x: npt.NDArray[np.generic],
    y: npt.NDArray[np.generic],
    thresholds: npt.NDArray[np.generic],
) -> list[dict[str, float | None]]:
    indexes = _sample_indexes(len(x))
    return [
        {
            "x": float(x[i]),
            "y": float(y[i]),
            "threshold": (
                float(thresholds[i])
                if i < len(thresholds) and isfinite(float(thresholds[i]))
                else None
            ),
        }
        for i in indexes
    ]


def _histogram(values: npt.NDArray[np.generic]) -> list[dict[str, float | int]]:
    counts, edges = np.histogram(
        np.asarray(values, dtype=np.float64), bins=min(20, max(1, len(values)))
    )
    return [
        {"start": float(edges[i]), "end": float(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]


def _error_by_range(
    predictions: npt.NDArray[np.float64], errors: npt.NDArray[np.float64]
) -> list[dict[str, float | int]]:
    count = min(10, max(1, len(predictions)))
    edges = np.linspace(
        float(np.min(predictions)), float(np.max(predictions)), count + 1
    )
    if edges[0] == edges[-1]:
        return [
            {
                "start": float(edges[0]),
                "end": float(edges[-1]),
                "mean_absolute_error": float(np.mean(errors)),
                "count": len(errors),
            }
        ]
    buckets = np.clip(np.digitize(predictions, edges[1:-1]), 0, count - 1)
    return [
        {
            "start": float(edges[i]),
            "end": float(edges[i + 1]),
            "mean_absolute_error": float(np.mean(errors[buckets == i])),
            "count": int(np.sum(buckets == i)),
        }
        for i in range(count)
        if np.any(buckets == i)
    ]


def _ranked(
    names: list[str], values: npt.NDArray[np.generic]
) -> list[dict[str, float | str]]:
    flat = np.ravel(np.asarray(values, dtype=np.float64))
    indexes = np.argsort(np.abs(flat))[::-1][:MAX_EXPLANATION_FEATURES]
    return [{"feature": names[int(i)], "value": float(flat[i])} for i in indexes]


def _label(value: object) -> str:
    return str(value.item() if isinstance(value, np.generic) else value)[:128]


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not isfinite(value):
        return None
    return value

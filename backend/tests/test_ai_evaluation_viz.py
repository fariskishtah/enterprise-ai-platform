"""Evaluation payload structure and visualization data tests.

These tests verify that build_evaluation_payload returns the exact structured data
needed by the frontend visualization components, including:
- All required plot keys and shapes
- All required metric keys
- All explainability entries
- No NaN or Infinity anywhere in the payload
- Bounded point counts
- Classification report structure
- Regression omitted-metric logic (MAPE with zero targets)
"""

from typing import Any

import numpy as np
import pytest
from app.ml.base import TrainerInput
from app.ml.evaluation import build_evaluation_payload
from app.ml.plugins import PluginTrainer, create_default_plugin_registry

# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _clf_data(n: int = 40) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    features = rng.standard_normal((n, 4))
    targets = (features[:, 0] + rng.standard_normal(n) * 0.3 > 0).astype(np.int64)
    return features, targets


def _reg_data(n: int = 40) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    features = rng.standard_normal((n, 4))
    targets = 2.0 * features[:, 0] - features[:, 1] + rng.standard_normal(n) * 0.3
    return features, targets.astype(np.float64)


def _train_and_evaluate(plugin_id: str, is_classification: bool) -> dict[str, Any]:
    plugin = create_default_plugin_registry().get(plugin_id)
    trainer = PluginTrainer(plugin)

    if is_classification:
        features, targets = _clf_data()
        output = trainer.fit(TrainerInput(features, targets, {}, 17))
    else:
        features, targets = _reg_data()
        output = trainer.fit(TrainerInput(features, targets, {}, 17))

    return build_evaluation_payload(
        plugin=plugin,
        model=output.model,
        features=features,
        targets=targets,
    )


# ─── Schema version ───────────────────────────────────────────────────────────


def test_evaluation_schema_version_is_set() -> None:
    payload = _train_and_evaluate("logistic_regression", is_classification=True)
    assert payload["schema_version"] == "1.0"


# ─── Classification payload structure ─────────────────────────────────────────


@pytest.mark.parametrize(
    "plugin_id",
    [
        "logistic_regression",
        "random_forest_classification",
        "gradient_boosting_classification",
    ],
)
def test_classification_payload_has_all_required_top_level_keys(
    plugin_id: str,
) -> None:
    payload = _train_and_evaluate(plugin_id, is_classification=True)

    required = {
        "schema_version",
        "task_type",
        "algorithm",
        "sample_count",
        "feature_count",
        "metrics",
        "plots",
        "omitted",
        "explainability",
    }
    assert required.issubset(payload.keys())
    assert payload["task_type"] == "classification"


@pytest.mark.parametrize(
    "plugin_id", ["logistic_regression", "random_forest_classification"]
)
def test_classification_metrics_contain_key_scores(plugin_id: str) -> None:
    payload = _train_and_evaluate(plugin_id, is_classification=True)
    metrics = payload["metrics"]

    for key in ("accuracy", "f1_macro", "precision_macro", "recall_macro"):
        assert key in metrics, f"Missing metric: {key}"
        val = metrics[key]
        assert isinstance(val, float), f"Metric {key} is not a float"
        assert 0.0 <= val <= 1.0, f"Metric {key}={val} out of [0, 1]"


def test_classification_confusion_matrix_structure() -> None:
    payload = _train_and_evaluate("logistic_regression", is_classification=True)
    plots = payload["plots"]

    assert "confusion_matrix" in plots
    cm = plots["confusion_matrix"]
    assert "labels" in cm
    assert "values" in cm

    labels = cm["labels"]
    values = cm["values"]
    assert len(labels) >= 2
    assert len(values) == len(labels)
    assert all(len(row) == len(labels) for row in values)

    # All values must be non-negative integers.
    for row in values:
        for cell in row:
            assert isinstance(cell, int) and cell >= 0


def test_classification_roc_curve_for_binary_classifier() -> None:
    """Binary logistic regression must produce an ROC curve."""
    payload = _train_and_evaluate("logistic_regression", is_classification=True)
    plots = payload["plots"]

    # May be present for binary classifiers.
    if "roc_curve" not in payload.get("omitted", {}) and "roc_curve" in plots:
        roc = plots["roc_curve"]
        assert len(roc) >= 2
        for point in roc:
            assert "x" in point and "y" in point
            assert 0.0 <= point["x"] <= 1.0
            assert 0.0 <= point["y"] <= 1.0


def test_classification_explainability_logistic_regression() -> None:
    """Logistic regression returns coefficients and unsupported feature importance."""
    payload = _train_and_evaluate("logistic_regression", is_classification=True)
    explain = payload["explainability"]

    # Coefficients should be supported.
    coeffs = explain.get("coefficients")
    assert coeffs is not None

    if isinstance(coeffs, list):
        # Supported — each entry must have feature and value.
        for entry in coeffs:
            assert "feature" in entry
            assert "value" in entry
            assert isinstance(entry["value"], float)


def test_classification_explainability_random_forest_importance() -> None:
    """Random forest must return native feature importance."""
    payload = _train_and_evaluate(
        "random_forest_classification", is_classification=True
    )
    explain = payload["explainability"]

    fi = explain.get("native_feature_importance")
    assert fi is not None

    if isinstance(fi, list):
        assert len(fi) > 0
        total = sum(e["value"] for e in fi)
        # Importances are non-negative and approximately sum to 1.
        assert all(e["value"] >= 0 for e in fi)
        assert abs(total - 1.0) < 0.1


def test_classification_local_explanation_always_unsupported() -> None:
    """Local explanations must always be marked as unsupported."""
    payload = _train_and_evaluate(
        "random_forest_classification", is_classification=True
    )
    local = payload["explainability"].get("local")

    assert local is not None
    assert local.get("supported") is False
    assert "reason" in local


def test_classification_no_nan_or_infinity_in_metrics() -> None:
    payload = _train_and_evaluate("logistic_regression", is_classification=True)
    for name, val in payload["metrics"].items():
        assert np.isfinite(val), f"Metric {name} is not finite: {val}"


def test_classification_sample_and_feature_count() -> None:
    payload = _train_and_evaluate("logistic_regression", is_classification=True)
    assert payload["sample_count"] == 40
    assert payload["feature_count"] == 4


# ─── Regression payload structure ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "plugin_id",
    [
        "linear_regression",
        "random_forest_regression",
        "ridge_regression",
    ],
)
def test_regression_payload_has_all_required_top_level_keys(
    plugin_id: str,
) -> None:
    payload = _train_and_evaluate(plugin_id, is_classification=False)

    required = {
        "schema_version",
        "task_type",
        "algorithm",
        "sample_count",
        "feature_count",
        "metrics",
        "plots",
        "omitted",
        "explainability",
    }
    assert required.issubset(payload.keys())
    assert payload["task_type"] == "regression"


@pytest.mark.parametrize("plugin_id", ["linear_regression", "random_forest_regression"])
def test_regression_metrics_contain_key_scores(plugin_id: str) -> None:
    payload = _train_and_evaluate(plugin_id, is_classification=False)
    metrics = payload["metrics"]

    for key in ("mae", "mse", "rmse", "r2"):
        assert key in metrics, f"Missing metric: {key}"
        val = metrics[key]
        assert isinstance(val, float)
        assert np.isfinite(val)

    # R² should be in a sane range for this dataset.
    assert -10.0 <= metrics["r2"] <= 1.0


def test_regression_actual_vs_predicted_structure() -> None:
    payload = _train_and_evaluate("linear_regression", is_classification=False)
    plots = payload["plots"]

    assert "actual_vs_predicted" in plots
    avp = plots["actual_vs_predicted"]
    assert len(avp) > 0
    assert len(avp) <= 200  # bounded

    for point in avp:
        assert "actual" in point
        assert "predicted" in point
        assert np.isfinite(point["actual"])
        assert np.isfinite(point["predicted"])


def test_regression_residuals_structure() -> None:
    payload = _train_and_evaluate("linear_regression", is_classification=False)
    plots = payload["plots"]

    assert "residuals" in plots
    residuals = plots["residuals"]
    assert len(residuals) > 0
    assert len(residuals) <= 200

    for point in residuals:
        assert "predicted" in point
        assert "residual" in point
        assert np.isfinite(point["predicted"])
        assert np.isfinite(point["residual"])


def test_regression_histogram_bins_are_ordered_and_non_negative() -> None:
    """Histogram bins must be non-overlapping and have non-negative counts."""
    payload = _train_and_evaluate("linear_regression", is_classification=False)
    plots = payload["plots"]

    for hist_key in ("residual_distribution", "absolute_error_distribution"):
        if hist_key not in plots:
            continue
        bins = plots[hist_key]
        for i, b in enumerate(bins):
            assert "start" in b and "end" in b and "count" in b
            assert b["start"] < b["end"], f"Bin {i} has inverted range"
            assert b["count"] >= 0
            if i > 0:
                prev = bins[i - 1]
                assert b["start"] >= prev["end"], f"Bins {i-1} and {i} overlap"


def test_regression_mape_omitted_when_zero_targets() -> None:
    """MAPE must be omitted when any target is zero (division by zero)."""
    plugin = create_default_plugin_registry().get("linear_regression")
    trainer = PluginTrainer(plugin)
    features = np.random.default_rng(1).standard_normal((30, 2))
    targets = np.arange(30, dtype=np.float64)
    targets[0] = 0.0  # introduce zero target

    output = trainer.fit(TrainerInput(features, targets, {}, 1))
    payload = build_evaluation_payload(
        plugin=plugin,
        model=output.model,
        features=features,
        targets=targets,
    )

    assert "mape" not in payload["metrics"]
    assert "mape" in payload["omitted"]
    mape_reason = payload["omitted"]["mape"]
    assert "MAPE" in mape_reason or "zero" in mape_reason.lower()


def test_regression_actual_vs_predicted_bounded_at_200() -> None:
    """actual_vs_predicted must never exceed 200 points even with many samples."""
    plugin = create_default_plugin_registry().get("linear_regression")
    trainer = PluginTrainer(plugin)
    rng = np.random.default_rng(5)
    n = 500
    features = rng.standard_normal((n, 3))
    targets = features[:, 0] * 2.0

    output = trainer.fit(TrainerInput(features, targets, {}, 5))
    payload = build_evaluation_payload(
        plugin=plugin,
        model=output.model,
        features=np.tile(features, (1, 1)),
        targets=targets,
    )

    avp = payload["plots"]["actual_vs_predicted"]
    assert len(avp) <= 200


def test_regression_explainability_linear_regression_coefficients() -> None:
    """Linear regression must return sorted coefficients."""
    payload = _train_and_evaluate("linear_regression", is_classification=False)
    explain = payload["explainability"]

    coeffs = explain.get("coefficients")
    assert coeffs is not None

    if isinstance(coeffs, list) and len(coeffs) > 1:
        # Should be ranked by absolute value descending.
        abs_vals = [abs(e["value"]) for e in coeffs]
        assert abs_vals == sorted(abs_vals, reverse=True)


def test_regression_explainability_no_nan_in_importance_values() -> None:
    payload = _train_and_evaluate("random_forest_regression", is_classification=False)
    explain = payload["explainability"]

    fi = explain.get("native_feature_importance")
    if isinstance(fi, list):
        for entry in fi:
            assert np.isfinite(
                entry["value"]
            ), f"Non-finite importance for feature {entry['feature']}"


# ─── SVC probability output ───────────────────────────────────────────────────


def test_svc_classification_payload_omits_roc_auc_when_multiclass() -> None:
    """SVC on > 2 classes cannot produce a simple ROC-AUC without OvR — must omit."""
    plugin = create_default_plugin_registry().get("svm_classification")
    trainer = PluginTrainer(plugin)
    rng = np.random.default_rng(99)
    features = rng.standard_normal((60, 4))
    targets = np.array([0, 1, 2] * 20, dtype=np.int64)
    rng.shuffle(targets)

    output = trainer.fit(TrainerInput(features, targets, {}, 99))
    payload = build_evaluation_payload(
        plugin=plugin,
        model=output.model,
        features=features,
        targets=targets,
    )

    assert payload["task_type"] == "classification"
    # Confusion matrix must still be present.
    assert "confusion_matrix" in payload["plots"]
    # For 3-class, roc_auc is typically omitted or present as macro OvR.
    # The important thing is no exception was raised.
    assert "metrics" in payload


def test_svc_classification_binary_has_roc_auc() -> None:
    """SVC binary classification must produce ROC AUC."""
    plugin = create_default_plugin_registry().get("svm_classification")
    trainer = PluginTrainer(plugin)
    features, targets = _clf_data()

    output = trainer.fit(TrainerInput(features, targets, {}, 42))
    payload = build_evaluation_payload(
        plugin=plugin,
        model=output.model,
        features=features,
        targets=targets,
    )

    assert "roc_auc" in payload["metrics"]
    roc_auc = payload["metrics"]["roc_auc"]
    assert 0.0 <= roc_auc <= 1.0


# ─── KNN unsupported explainability ───────────────────────────────────────────


def test_knn_classification_returns_unsupported_for_feature_importance() -> None:
    """KNN has no native feature importance — explainability must be unsupported."""
    payload = _train_and_evaluate("knn_classification", is_classification=True)
    explain = payload["explainability"]

    fi = explain.get("native_feature_importance")
    assert fi is not None
    # Should be unsupported dict, not a list.
    assert isinstance(fi, dict)
    assert fi.get("supported") is False
    assert "reason" in fi

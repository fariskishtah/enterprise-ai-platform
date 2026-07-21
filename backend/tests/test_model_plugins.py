"""Focused deterministic coverage for the core allowlisted model catalog."""

from pathlib import Path

import joblib  # type: ignore[import-untyped]
import numpy as np
import pytest
from app.ml.base import TrainerInput
from app.ml.domain import TaskType
from app.ml.evaluation import build_evaluation_payload
from app.ml.plugins import (
    DuplicateModelPluginError,
    ModelPluginError,
    ModelPluginRegistry,
    PluginTrainer,
    UnknownModelPluginError,
    create_default_plugin_registry,
)
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]


def _classification_data() -> tuple[np.ndarray, np.ndarray]:
    features = np.asarray(
        [[index / 10, (index % 3) / 3] for index in range(20)], dtype=np.float64
    )
    targets = np.asarray([0] * 10 + [1] * 10, dtype=np.int64)
    return features, targets


def _regression_data() -> tuple[np.ndarray, np.ndarray]:
    features = np.asarray(
        [[index / 10, (index % 4) / 4] for index in range(20)], dtype=np.float64
    )
    targets = 2.0 * features[:, 0] - 0.5 * features[:, 1]
    return features, targets.astype(np.float64)


def test_catalog_contains_every_required_core_algorithm() -> None:
    registry = create_default_plugin_registry()

    assert len(registry.all()) == 17
    assert {plugin.id for plugin in registry.all()} == {
        "logistic_regression",
        "decision_tree_classification",
        "random_forest_classification",
        "extra_trees_classification",
        "knn_classification",
        "svm_classification",
        "gradient_boosting_classification",
        "linear_regression",
        "ridge_regression",
        "lasso_regression",
        "elastic_net_regression",
        "decision_tree_regression",
        "random_forest_regression",
        "extra_trees_regression",
        "knn_regression",
        "svm_regression",
        "gradient_boosting_regression",
    }


def test_registry_rejects_duplicates_unknown_plugins_and_task_mismatch() -> None:
    source = create_default_plugin_registry()
    plugin = source.get("linear_regression")
    registry = ModelPluginRegistry()
    registry.register(plugin)

    with pytest.raises(DuplicateModelPluginError):
        registry.register(plugin)
    with pytest.raises(UnknownModelPluginError):
        registry.get("arbitrary.module.Estimator")
    with pytest.raises(ModelPluginError, match="does not support"):
        source.get("linear_regression", TaskType.CLASSIFICATION)


def test_plugin_parameters_reject_unknown_and_out_of_bounds_values() -> None:
    plugin = create_default_plugin_registry().get("logistic_regression")

    with pytest.raises(ModelPluginError, match="Unsupported hyperparameters"):
        plugin.validate_parameters({"__class__": "unsafe"})
    with pytest.raises(ModelPluginError, match="at most"):
        plugin.validate_parameters({"C": 100_000})


@pytest.mark.parametrize(
    "plugin_id",
    [
        "logistic_regression",
        "decision_tree_classification",
        "random_forest_classification",
        "extra_trees_classification",
        "knn_classification",
        "svm_classification",
        "gradient_boosting_classification",
    ],
)
def test_every_classification_plugin_trains_predicts_and_serializes(
    plugin_id: str, tmp_path: Path
) -> None:
    plugin = create_default_plugin_registry().get(plugin_id)
    trainer = PluginTrainer(plugin)
    features, targets = _classification_data()

    output = trainer.fit(
        TrainerInput(
            features=features,
            targets=targets,
            hyperparameters={"__scaler": "auto", "__imputer": "median"},
            random_seed=17,
        )
    )
    path = tmp_path / f"{plugin_id}.joblib"
    joblib.dump(output.model, path)
    restored = joblib.load(path)

    assert isinstance(restored, Pipeline)
    assert trainer.predict(restored, features[:3]).shape == (3,)


@pytest.mark.parametrize(
    "plugin_id",
    [
        "linear_regression",
        "ridge_regression",
        "lasso_regression",
        "elastic_net_regression",
        "decision_tree_regression",
        "random_forest_regression",
        "extra_trees_regression",
        "knn_regression",
        "svm_regression",
        "gradient_boosting_regression",
    ],
)
def test_every_regression_plugin_trains_predicts_and_serializes(
    plugin_id: str, tmp_path: Path
) -> None:
    plugin = create_default_plugin_registry().get(plugin_id)
    trainer = PluginTrainer(plugin)
    features, targets = _regression_data()

    output = trainer.fit(
        TrainerInput(
            features=features,
            targets=targets,
            hyperparameters={"__scaler": "auto", "__imputer": "mean"},
            random_seed=17,
        )
    )
    path = tmp_path / f"{plugin_id}.joblib"
    joblib.dump(output.model, path)
    restored = joblib.load(path)

    assert isinstance(restored, Pipeline)
    assert trainer.predict(restored, features[:3]).shape == (3,)


def test_evaluation_payload_contains_real_bounded_classification_outputs() -> None:
    plugin = create_default_plugin_registry().get("logistic_regression")
    features, targets = _classification_data()
    model = PluginTrainer(plugin).fit(TrainerInput(features, targets, {}, 17)).model

    payload = build_evaluation_payload(
        plugin=plugin,
        model=model,
        features=features,
        targets=targets,
    )

    assert payload["schema_version"] == "1.0"
    assert "roc_auc" in payload["metrics"]
    assert "confusion_matrix" in payload["plots"]
    assert payload["explainability"]["local"]["supported"] is False


def test_regression_evaluation_omits_unsafe_mape_and_bounds_plot_points() -> None:
    plugin = create_default_plugin_registry().get("linear_regression")
    features, targets = _regression_data()
    targets[0] = 0
    model = PluginTrainer(plugin).fit(TrainerInput(features, targets, {}, 17)).model

    payload = build_evaluation_payload(
        plugin=plugin,
        model=model,
        features=np.tile(features, (20, 1)),
        targets=np.tile(targets, 20),
    )

    assert "mape" not in payload["metrics"]
    assert "MAPE" in payload["omitted"]["mape"]
    assert len(payload["plots"]["actual_vs_predicted"]) <= 200

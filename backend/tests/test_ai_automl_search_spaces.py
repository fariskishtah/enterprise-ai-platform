"""Typed search-space, plugin contract, and deterministic sampling tests."""

import ast
import random
from pathlib import Path

import pytest
from app.ml.automl.sampling import (
    derive_trial_seed,
    sample_plugin_trial,
    search_space_fingerprint,
)
from app.ml.automl.search_space import (
    CategoricalSearchParameter,
    FloatSearchParameter,
    IntegerSearchParameter,
    PluginAutoMLSearchSpace,
    validate_narrowed_search_space,
)
from app.ml.domain import TaskType
from app.ml.plugins import ModelPluginError, create_default_plugin_registry
from pydantic import ValidationError


def test_typed_spaces_validate_bounds_steps_defaults_and_choices() -> None:
    integer = IntegerSearchParameter(name="depth", low=2, high=10, step=2, default=4)
    floating = FloatSearchParameter(
        name="alpha", low=0.001, high=10.0, default=1.0, log_scale=True
    )
    categorical = CategoricalSearchParameter(
        name="loss", choices=("squared_error", "huber"), default="squared_error"
    )
    assert integer.default == 4
    assert floating.log_scale is True
    assert categorical.default in categorical.choices


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (IntegerSearchParameter, {"name": "x", "low": 2, "high": 1, "default": 1}),
        (
            IntegerSearchParameter,
            {"name": "x", "low": 1, "high": 5, "step": 0, "default": 1},
        ),
        (
            IntegerSearchParameter,
            {"name": "x", "low": 1, "high": 5, "step": 2, "default": 2},
        ),
        (FloatSearchParameter, {"name": "x", "low": 2.0, "high": 1.0, "default": 1.0}),
        (
            FloatSearchParameter,
            {"name": "x", "low": 0.0, "high": 1.0, "default": 0.5, "log_scale": True},
        ),
        (
            FloatSearchParameter,
            {"name": "x", "low": 0.0, "high": float("nan"), "default": 0.5},
        ),
        (
            FloatSearchParameter,
            {"name": "x", "low": 0.0, "high": float("inf"), "default": 0.5},
        ),
        (CategoricalSearchParameter, {"name": "x", "choices": (), "default": "a"}),
        (
            CategoricalSearchParameter,
            {"name": "x", "choices": ("a", "a"), "default": "a"},
        ),
        (CategoricalSearchParameter, {"name": "x", "choices": ("a",), "default": "b"}),
    ],
)
def test_typed_spaces_reject_invalid_contracts(
    model: (
        type[IntegerSearchParameter]
        | type[FloatSearchParameter]
        | type[CategoricalSearchParameter]
    ),
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(values)


def test_names_and_choices_reject_expressions_and_module_paths() -> None:
    with pytest.raises(ValidationError):
        IntegerSearchParameter(name="os.system", low=1, high=2, default=1)
    with pytest.raises(ValidationError):
        CategoricalSearchParameter(
            name="kernel", choices=("sklearn.svm.SVC",), default="sklearn.svm.SVC"
        )
    with pytest.raises(ValidationError):
        CategoricalSearchParameter(
            name="estimator",
            choices=("RandomForestClassifier",),
            default="RandomForestClassifier",
        )


def test_narrowing_accepts_restrictions_and_rejects_broadening() -> None:
    owned = PluginAutoMLSearchSpace(
        plugin_id="safe_plugin",
        task_type=TaskType.REGRESSION,
        parameters=(
            IntegerSearchParameter(name="depth", low=2, high=20, step=2, default=4),
            CategoricalSearchParameter(
                name="loss", choices=("squared_error", "huber"), default="huber"
            ),
        ),
    )
    narrowed = PluginAutoMLSearchSpace(
        plugin_id="safe_plugin",
        task_type=TaskType.REGRESSION,
        parameters=(
            IntegerSearchParameter(name="depth", low=4, high=16, step=4, default=8),
            CategoricalSearchParameter(
                name="loss", choices=("huber",), default="huber"
            ),
        ),
    )
    assert validate_narrowed_search_space(owned, narrowed) is narrowed

    broadened = narrowed.model_copy(
        update={
            "parameters": (
                IntegerSearchParameter(name="depth", low=2, high=22, step=2, default=4),
                narrowed.parameters[1],
            )
        }
    )
    with pytest.raises(ValueError, match="broaden"):
        validate_narrowed_search_space(owned, broadened)


def test_plugin_contract_rejects_unknown_parameter_and_task_mismatch() -> None:
    plugin = create_default_plugin_registry().get("random_forest_regression")
    unknown = PluginAutoMLSearchSpace(
        plugin_id=plugin.id,
        task_type=TaskType.REGRESSION,
        parameters=(IntegerSearchParameter(name="n_jobs", low=1, high=2, default=1),),
    )
    with pytest.raises(ModelPluginError, match="unknown parameter"):
        plugin.validate_automl_search_space(unknown)

    assert plugin.automl_search_space is not None
    mismatch = plugin.automl_search_space.model_copy(
        update={"task_type": TaskType.CLASSIFICATION}
    )
    with pytest.raises(ModelPluginError, match="does not match"):
        plugin.validate_automl_search_space(mismatch)


def test_declared_plugin_spaces_are_explicit_safe_and_sampleable() -> None:
    registry = create_default_plugin_registry()
    supported = [plugin for plugin in registry.all() if plugin.automl_search_space]
    unsupported = [
        plugin.id for plugin in registry.all() if not plugin.automl_search_space
    ]
    assert unsupported == [
        "knn_classification",
        "knn_regression",
        "linear_regression",
        "svm_classification",
        "svm_regression",
    ]
    assert supported
    for plugin in supported:
        space = plugin.automl_search_space
        assert space is not None
        plugin.validate_automl_search_space(space)
        definition_names = {definition.name for definition in plugin.parameters}
        assert {parameter.name for parameter in space.parameters} <= definition_names
        assert not {"n_jobs", "random_state"} & {
            parameter.name for parameter in space.parameters
        }
        for trial_number in range(5):
            trial = sample_plugin_trial(
                plugin=plugin, study_seed=41, trial_number=trial_number
            )
            plugin.validate_parameters(trial.sampled_parameters)


def test_sampling_is_deterministic_canonical_and_global_random_independent() -> None:
    plugin = create_default_plugin_registry().get("random_forest_regression")
    random.seed(1)
    first = sample_plugin_trial(plugin=plugin, study_seed=7, trial_number=3)
    random.seed(999)
    second = sample_plugin_trial(plugin=plugin, study_seed=7, trial_number=3)
    assert first == second
    assert list(first.sampled_parameters) == sorted(first.sampled_parameters)

    different_trial = sample_plugin_trial(plugin=plugin, study_seed=7, trial_number=4)
    other_plugin = create_default_plugin_registry().get("extra_trees_regression")
    different_plugin = sample_plugin_trial(
        plugin=other_plugin, study_seed=7, trial_number=3
    )
    assert first.trial_seed != different_trial.trial_seed
    assert first.trial_seed != different_plugin.trial_seed


def test_sampling_rejects_space_broader_than_plugin_automl_contract() -> None:
    plugin = create_default_plugin_registry().get("random_forest_regression")
    owned = plugin.automl_search_space
    assert owned is not None
    broadened = owned.model_copy(
        update={
            "parameters": tuple(
                (
                    parameter.model_copy(update={"high": 225})
                    if parameter.name == "n_estimators"
                    else parameter
                )
                for parameter in owned.parameters
            )
        }
    )

    with pytest.raises(ValueError, match="broaden"):
        sample_plugin_trial(
            plugin=plugin,
            study_seed=7,
            trial_number=0,
            search_space=broadened,
        )


def test_sampling_respects_integer_float_log_and_categorical_spaces() -> None:
    registry = create_default_plugin_registry()
    tree = registry.get("random_forest_regression")
    logistic = registry.get("logistic_regression")
    for trial_number in range(20):
        tree_trial = sample_plugin_trial(
            plugin=tree, study_seed=9, trial_number=trial_number
        )
        assert 50 <= tree_trial.sampled_parameters["n_estimators"] <= 200
        assert (int(tree_trial.sampled_parameters["n_estimators"]) - 50) % 25 == 0
        logistic_trial = sample_plugin_trial(
            plugin=logistic, study_seed=9, trial_number=trial_number
        )
        assert 0.01 <= logistic_trial.sampled_parameters["C"] <= 100.0
        assert logistic_trial.sampled_parameters["class_weight"] in {
            "none",
            "balanced",
        }


def test_seed_and_space_fingerprints_are_stable_and_sensitive() -> None:
    plugin = create_default_plugin_registry().get("ridge_regression")
    assert plugin.automl_search_space is not None
    fingerprint = search_space_fingerprint(plugin.automl_search_space)
    assert fingerprint == search_space_fingerprint(plugin.automl_search_space)
    seed = derive_trial_seed(
        study_seed=5,
        plugin_id=plugin.id,
        trial_number=2,
        space_fingerprint=fingerprint,
    )
    assert seed == derive_trial_seed(
        study_seed=5,
        plugin_id=plugin.id,
        trial_number=2,
        space_fingerprint=fingerprint,
    )
    assert seed != derive_trial_seed(
        study_seed=5,
        plugin_id=plugin.id,
        trial_number=3,
        space_fingerprint=fingerprint,
    )


def test_automl_package_has_no_forbidden_runtime_boundaries_or_any() -> None:
    root = Path(__file__).resolve().parents[1] / "app/ml/automl"
    forbidden_imports = {
        "dramatiq",
        "fastapi",
        "mlflow",
        "optuna",
        "redis",
        "sqlalchemy",
    }
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "Any" not in names
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(
            module == prefix or module.startswith(prefix + ".")
            for module in imports
            for prefix in forbidden_imports
        )
        assert "eval(" not in path.read_text(encoding="utf-8")
        assert "exec(" not in path.read_text(encoding="utf-8")

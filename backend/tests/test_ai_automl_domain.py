"""Pure-domain tests for bounded AutoML study and trial contracts."""

import json

import pytest
from app.ml.automl.metrics import MetricDirection
from app.ml.automl.models import (
    AutoMLBudgetSpecification,
    AutoMLDataSpecificationReference,
    AutoMLStudySpecification,
    AutoMLStudyStatus,
    AutoMLTrialStatus,
    SamplerType,
    parameter_fingerprint,
)
from app.ml.automl.search_space import (
    IntegerSearchParameter,
    PluginAutoMLSearchSpace,
)
from app.ml.domain import TaskType
from app.ml.plugins import create_default_plugin_registry
from pydantic import ValidationError


def _data() -> AutoMLDataSpecificationReference:
    return AutoMLDataSpecificationReference(
        training_data_fingerprint="a" * 64,
        evaluation_data_fingerprint="b" * 64,
        training_row_count=40,
        evaluation_row_count=10,
        feature_count=4,
    )


def _budget(**updates: int) -> AutoMLBudgetSpecification:
    values = {
        "trial_budget": 8,
        "time_budget_seconds": 600,
        "per_trial_timeout_seconds": 60,
        "max_concurrent_trials": 1,
        "cross_validation_folds": 4,
        **updates,
    }
    return AutoMLBudgetSpecification(**values)


def _study(
    *,
    plugin_id: str = "random_forest_regression",
    task_type: TaskType = TaskType.REGRESSION,
    primary_metric: str = "rmse",
    direction: MetricDirection = MetricDirection.MINIMIZE,
    register_champion: bool = False,
    registered_model_name: str | None = None,
) -> AutoMLStudySpecification:
    plugin = create_default_plugin_registry().get(plugin_id)
    assert plugin.automl_search_space is not None
    return AutoMLStudySpecification(
        task_type=task_type,
        primary_metric=primary_metric,
        metric_direction=direction,
        sampler_type=SamplerType.RANDOM,
        random_seed=23,
        plugin_ids=(plugin_id,),
        plugin_search_spaces=(plugin.automl_search_space,),
        data=_data(),
        budget=_budget(),
        register_champion=register_champion,
        registered_model_name=registered_model_name,
    )


def test_study_contract_is_frozen_json_safe_and_round_trips() -> None:
    study = _study(
        register_champion=True,
        registered_model_name="automl_regression_model",
    )

    with pytest.raises(ValidationError):
        study.primary_metric = "mae"

    payload = study.model_dump_json()
    restored = AutoMLStudySpecification.model_validate_json(payload)
    assert restored == study
    assert json.loads(payload)["sampler_type"] == "random"
    assert len(study.fingerprint()) == 64


@pytest.mark.parametrize(
    ("task_type", "metric", "direction"),
    [
        (TaskType.REGRESSION, "accuracy", MetricDirection.MAXIMIZE),
        (TaskType.CLASSIFICATION, "rmse", MetricDirection.MINIMIZE),
        (TaskType.REGRESSION, "rmse", MetricDirection.MAXIMIZE),
        (TaskType.CLASSIFICATION, "made_up", MetricDirection.MAXIMIZE),
    ],
)
def test_study_rejects_invalid_task_metric_or_direction(
    task_type: TaskType,
    metric: str,
    direction: MetricDirection,
) -> None:
    plugin_id = (
        "random_forest_classification"
        if task_type is TaskType.CLASSIFICATION
        else "random_forest_regression"
    )
    with pytest.raises(ValidationError):
        _study(
            plugin_id=plugin_id,
            task_type=task_type,
            primary_metric=metric,
            direction=direction,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"trial_budget": 0},
        {"trial_budget": 101},
        {"cross_validation_folds": 1},
        {"cross_validation_folds": 11},
        {"time_budget_seconds": 59},
        {"time_budget_seconds": 86_401},
        {"per_trial_timeout_seconds": 9},
        {"per_trial_timeout_seconds": 21_601},
        {"max_concurrent_trials": 0},
        {"max_concurrent_trials": 5},
        {"time_budget_seconds": 60, "per_trial_timeout_seconds": 61},
        {"trial_budget": 1, "max_concurrent_trials": 2},
    ],
)
def test_budget_rejects_values_outside_conservative_limits(
    updates: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        _budget(**updates)


def test_study_rejects_duplicate_unknown_and_task_mismatched_plugins() -> None:
    regression = create_default_plugin_registry().get("random_forest_regression")
    classification = create_default_plugin_registry().get(
        "random_forest_classification"
    )
    assert regression.automl_search_space is not None
    assert classification.automl_search_space is not None

    common = dict(
        task_type=TaskType.REGRESSION,
        primary_metric="rmse",
        metric_direction=MetricDirection.MINIMIZE,
        data=_data(),
        budget=_budget(),
    )
    with pytest.raises(ValidationError, match="unique"):
        AutoMLStudySpecification(
            **common,
            plugin_ids=(regression.id, regression.id),
            plugin_search_spaces=(regression.automl_search_space,),
        )
    with pytest.raises(ValidationError, match="match the study task"):
        AutoMLStudySpecification(
            **common,
            plugin_ids=(classification.id,),
            plugin_search_spaces=(classification.automl_search_space,),
        )
    unknown = PluginAutoMLSearchSpace(
        plugin_id="unknown_regressor",
        task_type=TaskType.REGRESSION,
        parameters=(IntegerSearchParameter(name="depth", low=1, high=2, default=1),),
    )
    with pytest.raises(ValidationError, match="not available"):
        AutoMLStudySpecification(
            **common,
            plugin_ids=(unknown.plugin_id,),
            plugin_search_spaces=(unknown,),
        )


def test_champion_registration_requires_exact_safe_name() -> None:
    with pytest.raises(ValidationError, match="requires a registered model name"):
        _study(register_champion=True)
    with pytest.raises(ValidationError):
        _study(register_champion=True, registered_model_name="Unsafe.Model")
    with pytest.raises(ValidationError, match="requires champion registration"):
        _study(registered_model_name="unused_model")


def test_probability_metric_rejects_incompatible_plugin() -> None:
    plugin = create_default_plugin_registry().get("random_forest_classification")
    assert plugin.automl_search_space is not None
    incompatible = plugin.automl_search_space.model_copy(
        update={"probability_support": False}
    )
    with pytest.raises(ValidationError, match="probability support"):
        AutoMLStudySpecification(
            task_type=TaskType.CLASSIFICATION,
            primary_metric="roc_auc",
            metric_direction=MetricDirection.MAXIMIZE,
            plugin_ids=(plugin.id,),
            plugin_search_spaces=(incompatible,),
            data=_data(),
            budget=_budget(),
        )


def test_status_values_and_parameter_fingerprints_are_stable() -> None:
    assert {status.value for status in AutoMLStudyStatus} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }
    assert {status.value for status in AutoMLTrialStatus} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "pruned",
        "cancelled",
    }
    assert parameter_fingerprint({"depth": 4, "criterion": "gini"}) == (
        parameter_fingerprint({"criterion": "gini", "depth": 4})
    )
    assert parameter_fingerprint({"depth": 4}) != parameter_fingerprint({"depth": 5})

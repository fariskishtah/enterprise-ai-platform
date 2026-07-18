"""Complete typed local-training vertical-slice tests."""

import ast
import re
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import assert_type, cast
from uuid import uuid4

import numpy as np
import pytest
from app.ml.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactDestination,
    LocalArtifactManager,
)
from app.ml.base import BaseTrainer, TrainerInput
from app.ml.composition import (
    create_random_forest_classification_plan,
    create_random_forest_regression_plan,
)
from app.ml.engine import (
    TrainingEngine,
    TrainingExecutionInput,
    TrainingExecutionPlan,
    TrainingExecutionResult,
    TrainingModelTypeMismatchError,
)
from app.ml.factory import (
    TrainerFactory,
    TrainerNotRegisteredError,
    TrainerRegistration,
    TrainerRegistry,
)
from app.ml.metrics import (
    MetricsDataValidationError,
    RegressionMetricsEngine,
    RegressionMetricsReport,
)
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    RandomForestRegressorTrainer,
    TrainerDataValidationError,
)
from app.ml.trainers.random_forest.types import (
    ClassificationTargetArray,
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
)
from pydantic import ValidationError
from sklearn.ensemble import (  # type: ignore[import-untyped]
    RandomForestClassifier,
    RandomForestRegressor,
)

REGRESSION_FEATURES: FeatureArray = np.array(
    [
        [0.0, 0.0],
        [1.0, 1.0],
        [2.0, 2.0],
        [3.0, 3.0],
        [4.0, 4.0],
        [5.0, 5.0],
    ],
    dtype=np.float64,
)
REGRESSION_TARGETS: RegressionTargetArray = np.array(
    [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
    dtype=np.float64,
)
CLASSIFICATION_FEATURES: FeatureArray = np.array(
    [
        [0.0, 0.0],
        [0.5, 0.5],
        [1.0, 1.0],
        [3.0, 3.0],
        [3.5, 3.5],
        [4.0, 4.0],
    ],
    dtype=np.float64,
)
CLASSIFICATION_TARGETS: ClassificationTargetArray = np.array(
    [0, 0, 0, 1, 1, 1],
    dtype=np.int64,
)


class ProviderConstructionError(RuntimeError):
    """Sentinel exception raised by a failing trainer provider."""


def _assign_attribute(instance: object, name: str, value: object) -> None:
    setattr(instance, name, value)


def _trainer_factory() -> tuple[TrainerFactory, TrainerRegistry]:
    registry = TrainerRegistry()
    registry.register(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    registry.register(RANDOM_FOREST_CLASSIFIER_REGISTRATION)
    return TrainerFactory(registry), registry


def _regression_training_input(
    *,
    features: FeatureArray = REGRESSION_FEATURES,
    targets: RegressionTargetArray = REGRESSION_TARGETS,
    hyperparameters: dict[str, object] | None = None,
) -> TrainerInput[FeatureArray, RegressionTargetArray]:
    return TrainerInput(
        features=features,
        targets=targets,
        hyperparameters=(
            {"n_estimators": 5, "n_jobs": 1}
            if hyperparameters is None
            else hyperparameters
        ),
        random_seed=17,
    )


def _regression_plan(
    *,
    training_input: (
        TrainerInput[
            FeatureArray,
            RegressionTargetArray,
        ]
        | None
    ) = None,
    evaluation_features: FeatureArray = REGRESSION_FEATURES,
    evaluation_targets: RegressionTargetArray = REGRESSION_TARGETS,
) -> TrainingExecutionPlan[
    RandomForestRegressorTrainer,
    FeatureArray,
    RegressionTargetArray,
    RandomForestRegressor,
    RegressionPredictionArray,
    RegressionMetricsReport,
]:
    return create_random_forest_regression_plan(
        training_input=(
            _regression_training_input() if training_input is None else training_input
        ),
        evaluation_features=evaluation_features,
        evaluation_targets=evaluation_targets,
    )


def test_regression_training_engine_executes_complete_local_flow(
    tmp_path: Path,
) -> None:
    """Regression flows from registration through a workflow adapter."""
    trainer_factory, registry = _trainer_factory()
    artifact_manager = LocalArtifactManager(tmp_path / "artifacts")
    run_id = uuid4()
    engine = TrainingEngine(
        trainer_factory=trainer_factory,
        artifact_manager=artifact_manager,
        run_id_factory=lambda: run_id,
    )
    plan = _regression_plan()

    result = engine.execute(plan)

    assert_type(
        result,
        TrainingExecutionResult[RandomForestRegressor, RegressionMetricsReport],
    )
    assert result.run_id == run_id
    assert result.key == RANDOM_FOREST_REGRESSOR_REGISTRATION.key
    assert isinstance(result.model, RandomForestRegressor)
    assert isinstance(result.metrics_report, RegressionMetricsReport)
    assert result.training_duration_seconds >= 0.0
    assert result.artifact.path.is_file()
    assert result.artifact.size_bytes > 0
    loaded = artifact_manager.load(result.artifact, plan.expected_model_type)
    assert isinstance(loaded, RandomForestRegressor)

    workflow_result = result.to_training_result()
    assert workflow_result.success is True
    assert workflow_result.model_version == str(run_id)
    assert set(workflow_result.metrics) == {"mae", "mse", "rmse", "r2"}
    assert workflow_result.artifact_path == result.artifact.path
    assert workflow_result.duration_seconds == result.training_duration_seconds
    assert workflow_result.error_message is None
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(result, "run_id", uuid4())
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(
            plan.execution_input,
            "evaluation_features",
            REGRESSION_FEATURES,
        )
    assert registry.registered_keys() == (
        RANDOM_FOREST_CLASSIFIER_REGISTRATION.key,
        RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
    )


def test_classification_training_engine_executes_complete_local_flow(
    tmp_path: Path,
) -> None:
    """Classification preserves its model, report, artifact, and adapter types."""
    trainer_factory, _ = _trainer_factory()
    artifact_manager = LocalArtifactManager(tmp_path / "artifacts")
    run_id = uuid4()
    engine = TrainingEngine(
        trainer_factory=trainer_factory,
        artifact_manager=artifact_manager,
        run_id_factory=lambda: run_id,
    )
    training_input = TrainerInput(
        features=CLASSIFICATION_FEATURES,
        targets=CLASSIFICATION_TARGETS,
        hyperparameters={"n_estimators": 5, "n_jobs": 1},
        random_seed=19,
    )
    plan = create_random_forest_classification_plan(
        training_input=training_input,
        evaluation_features=CLASSIFICATION_FEATURES,
        evaluation_targets=CLASSIFICATION_TARGETS,
    )

    result = engine.execute(plan)

    assert isinstance(result.model, RandomForestClassifier)
    assert result.key == RANDOM_FOREST_CLASSIFIER_REGISTRATION.key
    assert result.training_duration_seconds >= 0.0
    assert result.artifact.path.is_file()
    loaded = artifact_manager.load(result.artifact, plan.expected_model_type)
    assert isinstance(loaded, RandomForestClassifier)
    workflow_result = result.to_training_result()
    assert workflow_result.model_version == str(run_id)
    assert set(workflow_result.metrics) == {
        "accuracy",
        "precision_macro",
        "recall_macro",
        "f1_macro",
    }


def test_training_engine_does_not_retain_model_on_trainer(tmp_path: Path) -> None:
    """The concrete trainer remains stateless after engine-driven fitting."""
    captured_trainers: list[RandomForestRegressorTrainer] = []

    def create_captured_trainer() -> RandomForestRegressorTrainer:
        trainer = RandomForestRegressorTrainer()
        captured_trainers.append(trainer)
        return trainer

    registration = TrainerRegistration(
        key=RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
        provider=create_captured_trainer,
    )
    registry = TrainerRegistry()
    registry.register(registration)
    execution_input: TrainingExecutionInput[
        RandomForestRegressorTrainer,
        FeatureArray,
        RegressionTargetArray,
    ] = TrainingExecutionInput(
        registration=registration,
        training_input=_regression_training_input(),
        evaluation_features=REGRESSION_FEATURES,
        evaluation_targets=REGRESSION_TARGETS,
    )
    plan = TrainingExecutionPlan(
        execution_input=execution_input,
        trainer_contract=lambda trainer: trainer,
        metrics_engine=RegressionMetricsEngine(),
        expected_model_type=RandomForestRegressor,
    )
    engine = TrainingEngine(
        trainer_factory=TrainerFactory(registry),
        artifact_manager=LocalArtifactManager(tmp_path / "artifacts"),
    )

    engine.execute(plan)

    assert len(captured_trainers) == 1
    assert "model" not in vars(captured_trainers[0])


def test_training_engine_rejects_unregistered_token(tmp_path: Path) -> None:
    """The engine preserves explicit registry membership requirements."""
    engine = TrainingEngine(
        trainer_factory=TrainerFactory(TrainerRegistry()),
        artifact_manager=LocalArtifactManager(tmp_path / "artifacts"),
    )

    with pytest.raises(TrainerNotRegisteredError):
        engine.execute(_regression_plan())


def test_training_engine_propagates_invalid_parameters(tmp_path: Path) -> None:
    """Pydantic parameter validation is not converted into engine failures."""
    trainer_factory, _ = _trainer_factory()
    artifact_manager = LocalArtifactManager(tmp_path / "artifacts")
    plan = _regression_plan(
        training_input=_regression_training_input(
            hyperparameters={"n_estimators": 0},
        ),
    )

    with pytest.raises(ValidationError):
        TrainingEngine(
            trainer_factory=trainer_factory,
            artifact_manager=artifact_manager,
        ).execute(plan)

    assert not tuple(artifact_manager.root_directory.rglob("model.joblib"))


def test_training_engine_propagates_invalid_training_arrays(tmp_path: Path) -> None:
    """Trainer data validation remains authoritative during orchestration."""
    trainer_factory, _ = _trainer_factory()
    invalid_features: FeatureArray = np.array([0.0, 1.0], dtype=np.float64)
    plan = _regression_plan(
        training_input=_regression_training_input(features=invalid_features),
    )

    with pytest.raises(TrainerDataValidationError, match="2-dimensional"):
        TrainingEngine(
            trainer_factory=trainer_factory,
            artifact_manager=LocalArtifactManager(tmp_path / "artifacts"),
        ).execute(plan)


def test_training_engine_propagates_invalid_evaluation_arrays(
    tmp_path: Path,
) -> None:
    """Prediction feature validation occurs before metrics and persistence."""
    trainer_factory, _ = _trainer_factory()
    invalid_features: FeatureArray = np.array([0.0, 1.0], dtype=np.float64)

    with pytest.raises(TrainerDataValidationError, match="2-dimensional"):
        TrainingEngine(
            trainer_factory=trainer_factory,
            artifact_manager=LocalArtifactManager(tmp_path / "artifacts"),
        ).execute(_regression_plan(evaluation_features=invalid_features))


def test_training_engine_propagates_metrics_length_mismatch(
    tmp_path: Path,
) -> None:
    """Metrics validation failures prevent artifact persistence."""
    trainer_factory, _ = _trainer_factory()
    artifact_manager = LocalArtifactManager(tmp_path / "artifacts")
    evaluation_targets: RegressionTargetArray = np.array([0.0], dtype=np.float64)
    plan = _regression_plan(evaluation_targets=evaluation_targets)

    with pytest.raises(MetricsDataValidationError, match="lengths must be equal"):
        TrainingEngine(
            trainer_factory=trainer_factory,
            artifact_manager=artifact_manager,
        ).execute(plan)

    assert not tuple(artifact_manager.root_directory.rglob("model.joblib"))


def test_training_engine_propagates_artifact_overwrite(tmp_path: Path) -> None:
    """An existing UUID destination is never overwritten by orchestration."""
    trainer_factory, _ = _trainer_factory()
    artifact_manager = LocalArtifactManager(tmp_path / "artifacts")
    run_id = uuid4()
    artifact_manager.save(
        RandomForestRegressor(n_estimators=1),
        ArtifactDestination(
            key=RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
            run_id=run_id,
        ),
    )

    with pytest.raises(ArtifactAlreadyExistsError, match="already exists"):
        TrainingEngine(
            trainer_factory=trainer_factory,
            artifact_manager=artifact_manager,
            run_id_factory=lambda: run_id,
        ).execute(_regression_plan())


def test_training_engine_detects_wrong_expected_model_type(tmp_path: Path) -> None:
    """A misconfigured plan cannot persist a differently typed fitted model."""
    trainer_factory, _ = _trainer_factory()
    plan = _regression_plan()
    invalid_plan = TrainingExecutionPlan(
        execution_input=plan.execution_input,
        trainer_contract=plan.trainer_contract,
        metrics_engine=plan.metrics_engine,
        expected_model_type=cast(
            type[RandomForestRegressor],
            RandomForestClassifier,
        ),
    )

    with pytest.raises(TrainingModelTypeMismatchError, match="expected"):
        TrainingEngine(
            trainer_factory=trainer_factory,
            artifact_manager=LocalArtifactManager(tmp_path / "artifacts"),
        ).execute(invalid_plan)


def test_training_engine_propagates_provider_construction_error(
    tmp_path: Path,
) -> None:
    """Provider-specific construction failures remain visible to callers."""

    def raise_during_construction() -> RandomForestRegressorTrainer:
        raise ProviderConstructionError("constructor failed")

    registration = TrainerRegistration(
        key=RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
        provider=raise_during_construction,
    )
    registry = TrainerRegistry()
    registry.register(registration)
    execution_input: TrainingExecutionInput[
        RandomForestRegressorTrainer,
        FeatureArray,
        RegressionTargetArray,
    ] = TrainingExecutionInput(
        registration=registration,
        training_input=_regression_training_input(),
        evaluation_features=REGRESSION_FEATURES,
        evaluation_targets=REGRESSION_TARGETS,
    )
    plan = TrainingExecutionPlan(
        execution_input=execution_input,
        trainer_contract=lambda trainer: trainer,
        metrics_engine=RegressionMetricsEngine(),
        expected_model_type=RandomForestRegressor,
    )

    with pytest.raises(ProviderConstructionError, match="constructor failed"):
        TrainingEngine(
            trainer_factory=TrainerFactory(registry),
            artifact_manager=LocalArtifactManager(tmp_path / "artifacts"),
        ).execute(plan)


def _imported_modules(package_directory: Path) -> set[str]:
    imported_modules: set[str] = set()
    for module_path in package_directory.rglob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)
    return imported_modules


def test_ai_packages_preserve_dependency_boundaries() -> None:
    """Training, evaluation, persistence, and orchestration stay separated."""
    ml_directory = Path(__file__).parents[1] / "app" / "ml"
    trainer_imports = _imported_modules(ml_directory / "trainers")
    metrics_imports = _imported_modules(ml_directory / "metrics")
    artifact_imports = _imported_modules(ml_directory / "artifacts")
    engine_imports = _imported_modules(ml_directory / "engine")

    assert not any(
        imported.startswith(("app.ml.metrics", "app.ml.artifacts"))
        for imported in trainer_imports
    )
    assert not any(
        imported.startswith(("app.ml.trainers", "app.ml.artifacts"))
        for imported in metrics_imports
    )
    assert not any(
        imported.startswith(("app.ml.trainers", "app.ml.metrics"))
        for imported in artifact_imports
    )
    assert not any(
        imported.startswith(("sklearn", "app.ml.trainers"))
        for imported in engine_imports
    )


def test_ai_application_has_no_any_or_broad_import_ignores() -> None:
    """AI source keeps explicit types and only exact untyped-import boundaries."""
    ml_directory = Path(__file__).parents[1] / "app" / "ml"
    ignore_pattern = re.compile(r"# type: ignore\[([^]]+)]")
    for module_path in ml_directory.rglob("*.py"):
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(
            isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(tree)
        )
        for line in source.splitlines():
            if "# type: ignore" in line:
                match = ignore_pattern.search(line)
                assert match is not None
                assert match.group(1) == "import-untyped"


def test_ai_application_has_no_global_trainer_registry() -> None:
    """Registry construction remains an explicit caller-owned operation."""
    ml_directory = Path(__file__).parents[1] / "app" / "ml"
    for module_path in ml_directory.rglob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            assert not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "TrainerRegistry"
            )


def test_base_trainer_contract_remains_minimal() -> None:
    """The vertical slice adds no responsibilities to BaseTrainer."""
    assert BaseTrainer.__abstractmethods__ == frozenset({"key", "fit", "predict"})

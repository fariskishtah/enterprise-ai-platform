"""Root-scoped local Joblib artifact manager tests."""

import ast
from pathlib import Path
from uuid import uuid4

import pytest
from app.ml.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactDestination,
    ArtifactFormat,
    ArtifactInfo,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactTypeMismatchError,
    LocalArtifactManager,
)
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from sklearn.ensemble import (  # type: ignore[import-untyped]
    RandomForestClassifier,
    RandomForestRegressor,
)

REGRESSION_KEY = TrainerKey(
    algorithm=AlgorithmType.RANDOM_FOREST,
    task_type=TaskType.REGRESSION,
)
CLASSIFICATION_KEY = TrainerKey(
    algorithm=AlgorithmType.RANDOM_FOREST,
    task_type=TaskType.CLASSIFICATION,
)


def test_local_artifact_manager_saves_and_loads_regressor(tmp_path: Path) -> None:
    """A saved regressor retains its concrete type and metadata."""
    manager = LocalArtifactManager(tmp_path / "artifacts")
    model = RandomForestRegressor(n_estimators=2, random_state=7)
    run_id = uuid4()

    artifact = manager.save(
        model,
        ArtifactDestination(key=REGRESSION_KEY, run_id=run_id),
    )
    loaded = manager.load(artifact, RandomForestRegressor)

    assert isinstance(loaded, RandomForestRegressor)
    assert artifact.path == (
        manager.root_directory
        / "random_forest"
        / "regression"
        / str(run_id)
        / "model.joblib"
    )
    assert artifact.path.is_file()
    assert artifact.size_bytes == artifact.path.stat().st_size
    assert artifact.size_bytes > 0
    assert artifact.format is ArtifactFormat.JOBLIB


def test_local_artifact_manager_saves_and_loads_classifier(tmp_path: Path) -> None:
    """A saved classifier retains its concrete type."""
    manager = LocalArtifactManager(tmp_path / "artifacts")
    model = RandomForestClassifier(n_estimators=2, random_state=11)

    artifact = manager.save(
        model,
        ArtifactDestination(key=CLASSIFICATION_KEY, run_id=uuid4()),
    )
    loaded = manager.load(artifact, RandomForestClassifier)

    assert isinstance(loaded, RandomForestClassifier)
    assert artifact.path.parts[-4:-1] == (
        "random_forest",
        "classification",
        artifact.path.parent.name,
    )


def test_local_artifact_manager_rejects_wrong_expected_type(tmp_path: Path) -> None:
    """Dynamically loaded objects are runtime-checked before return."""
    manager = LocalArtifactManager(tmp_path / "artifacts")
    artifact = manager.save(
        RandomForestRegressor(n_estimators=1),
        ArtifactDestination(key=REGRESSION_KEY, run_id=uuid4()),
    )

    with pytest.raises(ArtifactTypeMismatchError, match="expected"):
        manager.load(artifact, RandomForestClassifier)


def test_local_artifact_manager_rejects_missing_artifact(tmp_path: Path) -> None:
    """Missing in-root artifact files fail with a focused exception."""
    manager = LocalArtifactManager(tmp_path / "artifacts")
    missing = ArtifactInfo(
        path=manager.root_directory / "random_forest/regression/missing/model.joblib",
        size_bytes=0,
        format=ArtifactFormat.JOBLIB,
    )

    with pytest.raises(ArtifactNotFoundError, match="does not exist"):
        manager.load(missing, RandomForestRegressor)


def test_local_artifact_manager_rejects_path_traversal(tmp_path: Path) -> None:
    """Artifact metadata cannot direct loading outside the configured root."""
    manager = LocalArtifactManager(tmp_path / "artifacts")
    outside = ArtifactInfo(
        path=tmp_path / "outside.joblib",
        size_bytes=0,
        format=ArtifactFormat.JOBLIB,
    )

    with pytest.raises(ArtifactPathError, match="outside root"):
        manager.load(outside, RandomForestRegressor)


def test_local_artifact_manager_rejects_overwrite(tmp_path: Path) -> None:
    """Saving the same run destination twice never overwrites a model."""
    manager = LocalArtifactManager(tmp_path / "artifacts")
    destination = ArtifactDestination(key=REGRESSION_KEY, run_id=uuid4())
    manager.save(RandomForestRegressor(n_estimators=1), destination)

    with pytest.raises(ArtifactAlreadyExistsError, match="already exists"):
        manager.save(RandomForestRegressor(n_estimators=2), destination)


def test_different_run_ids_create_different_artifact_paths(tmp_path: Path) -> None:
    """Run UUIDs isolate otherwise identical algorithm/task artifacts."""
    manager = LocalArtifactManager(tmp_path / "artifacts")

    first = manager.save(
        RandomForestRegressor(n_estimators=1),
        ArtifactDestination(key=REGRESSION_KEY, run_id=uuid4()),
    )
    second = manager.save(
        RandomForestRegressor(n_estimators=1),
        ArtifactDestination(key=REGRESSION_KEY, run_id=uuid4()),
    )

    assert first.path != second.path
    assert first.path.is_file()
    assert second.path.is_file()


def test_artifact_managers_keep_instance_specific_roots(tmp_path: Path) -> None:
    """No global directory couples separate local manager instances."""
    first_manager = LocalArtifactManager(tmp_path / "first")
    second_manager = LocalArtifactManager(tmp_path / "second")
    destination = ArtifactDestination(key=REGRESSION_KEY, run_id=uuid4())

    first = first_manager.save(RandomForestRegressor(n_estimators=1), destination)
    second = second_manager.save(RandomForestRegressor(n_estimators=1), destination)

    assert first.path != second.path
    assert first.path.is_relative_to(first_manager.root_directory)
    assert second.path.is_relative_to(second_manager.root_directory)


def test_artifact_info_rejects_negative_size() -> None:
    """Serialized size metadata cannot be negative."""
    with pytest.raises(ValueError, match="greater than or equal to zero"):
        ArtifactInfo(
            path=Path("model.joblib"),
            size_bytes=-1,
            format=ArtifactFormat.JOBLIB,
        )


def test_artifact_package_has_no_mlflow_dependency() -> None:
    """Local serialization remains independent from experiment tracking."""
    artifact_dir = Path(__file__).parents[1] / "app" / "ml" / "artifacts"
    imported_modules: set[str] = set()
    for module_path in artifact_dir.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

    assert not any(module.startswith("mlflow") for module in imported_modules)

"""Stable architectural-boundary tests for the tracked AI Core slice."""

import ast
from pathlib import Path

import pytest
from app.config.settings import Settings
from app.dependencies.services import get_ai_trainer_registry
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
)
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _assert_no_import_prefixes(path: Path, prefixes: tuple[str, ...]) -> None:
    imported = _imports(path)
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported
        for prefix in prefixes
    ), f"{path} crossed a protected architecture boundary: {sorted(imported)}"


def test_trainers_metrics_and_generic_engine_remain_infrastructure_free() -> None:
    """Core fit/evaluate/orchestrate components do not acquire MLOps or API work."""
    trainer_forbidden = (
        "app.ml.tracking",
        "app.ml.registry",
        "app.ml.services",
        "app.api",
        "mlflow",
        "joblib",
    )
    for path in (APP_ROOT / "ml/trainers/random_forest").glob("*.py"):
        _assert_no_import_prefixes(path, trainer_forbidden)

    metrics_forbidden = (
        "app.ml.tracking",
        "app.ml.registry",
        "app.ml.services",
        "app.api",
        "mlflow",
    )
    for path in (APP_ROOT / "ml/metrics").glob("*.py"):
        _assert_no_import_prefixes(path, metrics_forbidden)

    _assert_no_import_prefixes(
        APP_ROOT / "ml/engine/training.py",
        ("mlflow", "app.ml.tracking", "app.ml.registry", "app.ml.services"),
    )


def test_ai_router_has_no_estimator_or_persistence_implementation_imports() -> None:
    """FastAPI delegates sklearn, MLflow, and Joblib work to supplied services."""
    _assert_no_import_prefixes(
        APP_ROOT / "api/routes/ai.py",
        ("sklearn", "mlflow", "joblib"),
    )


def test_registered_model_loader_is_only_prediction_side_mlflow_importer() -> None:
    """Generic application services do not download MLflow artifacts directly."""
    mlflow_importers = {
        path.name: sorted(
            module for module in _imports(path) if module.startswith("mlflow")
        )
        for path in (APP_ROOT / "ml/services").glob("*.py")
        if any(module.startswith("mlflow") for module in _imports(path))
    }
    assert mlflow_importers == {"loader.py": ["mlflow.artifacts"]}


def test_public_contract_modules_do_not_expose_mlflow_sdk_types() -> None:
    """Platform requests, results, and abstract ports remain SDK-independent."""
    contract_paths = (
        APP_ROOT / "ml/tracking/base.py",
        APP_ROOT / "ml/tracking/models.py",
        APP_ROOT / "ml/registry/base.py",
        APP_ROOT / "ml/registry/models.py",
        APP_ROOT / "ml/services/types.py",
    )
    for path in contract_paths:
        _assert_no_import_prefixes(path, ("mlflow",))


def test_new_ai_application_code_has_no_any_never_or_typing_cast() -> None:
    """The new vertical slice keeps explicit static and runtime boundaries."""
    paths = [
        *sorted((APP_ROOT / "ml/tracking").glob("*.py")),
        *sorted((APP_ROOT / "ml/registry").glob("*.py")),
        *sorted((APP_ROOT / "ml/services").glob("*.py")),
        APP_ROOT / "ml/composition/random_forest.py",
        APP_ROOT / "api/routes/ai.py",
        APP_ROOT / "schemas/ai.py",
    ]
    forbidden_names = {"Any", "Never", "cast"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        used_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert used_names.isdisjoint(forbidden_names), path


def test_application_type_ignores_are_narrow_third_party_import_ignores() -> None:
    """No broad suppression was introduced for unavailable package metadata."""
    ignore_lines = [
        line.strip()
        for path in APP_ROOT.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if "type: ignore" in line
    ]
    assert ignore_lines
    assert all("# type: ignore[import-untyped]" in line for line in ignore_lines)


def test_dependency_factory_does_not_mutate_a_global_trainer_registry() -> None:
    """Each dependency graph receives a fresh explicitly populated registry."""
    first = get_ai_trainer_registry()
    second = get_ai_trainer_registry()
    expected_keys = (
        RANDOM_FOREST_CLASSIFIER_REGISTRATION.key,
        RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
    )

    assert first is not second
    assert first.registered_keys() == expected_keys
    assert second.registered_keys() == expected_keys


def test_background_worker_and_promotion_preserve_architecture_boundaries() -> None:
    """Queue, worker, trainers, policies, and routes retain explicit ownership."""
    _assert_no_import_prefixes(
        APP_ROOT / "ml/jobs/tasks.py",
        ("fastapi", "app.api", "app.dependencies"),
    )
    _assert_no_import_prefixes(
        APP_ROOT / "ml/jobs/worker.py",
        ("fastapi", "app.api", "app.dependencies", "dramatiq", "redis"),
    )
    _assert_no_import_prefixes(
        APP_ROOT / "ml/promotion/policy.py",
        ("fastapi", "mlflow", "app.api", "app.repositories"),
    )
    _assert_no_import_prefixes(
        APP_ROOT / "ml/engine/training.py",
        ("dramatiq", "redis", "app.ml.jobs", "app.ml.promotion"),
    )
    for path in (APP_ROOT / "ml/trainers").rglob("*.py"):
        _assert_no_import_prefixes(
            path,
            ("app.ml.jobs", "app.ml.promotion", "dramatiq", "redis"),
        )
    _assert_no_import_prefixes(
        APP_ROOT / "api/routes/ai_governance.py",
        ("app.models.ai_governance", "dramatiq", "redis", "mlflow"),
    )


def test_background_queue_boundary_has_no_dataset_or_automatic_champion_payload() -> (
    None
):
    """The broker carries only UUID text and worker completion assigns candidate."""
    queue_source = (APP_ROOT / "ml/jobs/queue.py").read_text(encoding="utf-8")
    task_source = (APP_ROOT / "ml/jobs/tasks.py").read_text(encoding="utf-8")
    worker_source = (APP_ROOT / "ml/jobs/worker.py").read_text(encoding="utf-8")

    assert "execute_training_job.send(str(training_job_id))" in queue_source
    assert "training_features" not in queue_source
    assert '"candidate"' in task_source
    assert '"champion"' not in task_source
    assert '"champion"' not in worker_source


def test_new_job_and_promotion_application_code_has_no_any() -> None:
    """The production-oriented slice retains explicit application types."""
    paths = [
        *sorted((APP_ROOT / "ml/jobs").glob("*.py")),
        *sorted((APP_ROOT / "ml/promotion").glob("*.py")),
        APP_ROOT / "repositories/ai_governance.py",
        APP_ROOT / "models/ai_governance.py",
        APP_ROOT / "api/routes/ai_governance.py",
        APP_ROOT / "schemas/ai_governance.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        used_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "Any" not in used_names, path


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ai_artifact_root", ""),
        ("mlflow_tracking_uri", ""),
        ("ai_default_registered_model_prefix", "Unsafe-Prefix"),
        ("training_queue_name", "unsafe queue"),
        ("training_job_max_attempts", 0),
        ("training_job_retry_base_seconds", 0),
        ("training_job_stale_after_seconds", 0),
        ("promotion_regression_min_r2", float("inf")),
        ("promotion_regression_min_relative_rmse_improvement", 1.1),
        ("promotion_classification_min_accuracy", -0.1),
        ("promotion_classification_min_f1_improvement", 1.1),
    ],
)
def test_ai_settings_reject_empty_paths_and_unsafe_prefixes(
    field: str,
    value: str,
) -> None:
    """Environment configuration validates required AI integration boundaries."""
    values: dict[str, object] = {
        "database_url": "sqlite+aiosqlite://",
        "redis_url": "redis://localhost:6379/0",
        "secret_key": "test-secret-key-with-sufficient-entropy",
        field: value,
    }
    with pytest.raises(ValidationError):
        Settings.model_validate(values)

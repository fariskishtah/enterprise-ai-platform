"""Static retraining ownership and governance boundary tests."""

import ast
from pathlib import Path

RETRAINING_ROOT = Path("app/ml/retraining")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_pure_policy_has_no_framework_or_integration_imports() -> None:
    imports = _imports(RETRAINING_ROOT / "policy.py")

    assert not any(
        module.startswith(("fastapi", "sqlalchemy", "mlflow", "dramatiq", "joblib"))
        for module in imports
    )


def test_retraining_package_has_no_direct_promotion_or_artifact_loading_call() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in RETRAINING_ROOT.glob("*.py")
    )

    assert ".promote(" not in source
    assert ".assign_alias(" not in source
    assert "joblib" not in source.lower()
    assert "typing import Any" not in source


def test_prediction_paths_do_not_trigger_retraining() -> None:
    prediction_paths = (
        Path("app/api/routes/ai.py"),
        Path("app/ml/monitoring/capture.py"),
        Path("app/ml/services/prediction.py"),
    )

    assert not any(
        module.startswith("app.ml.retraining")
        for path in prediction_paths
        for module in _imports(path)
    )


def test_service_reuses_existing_background_submission_boundary() -> None:
    source = (RETRAINING_ROOT / "service.py").read_text(encoding="utf-8")

    assert "TrainingJobService" in source
    assert "await self._jobs.submit(" in source
    assert "TrainingJobWorker" not in source
    assert "execute_training_job" not in source

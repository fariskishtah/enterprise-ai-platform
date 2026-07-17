"""MLOps Alembic migration tests."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_alembic_head_creates_mlops_tables_and_indexes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Alembic head creates the Sprint 8 MLOps tables and indexes."""
    database_path = tmp_path / "mlops-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-sufficient-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
        experiment_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('experiments')")
        }
        run_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('training_runs')")
        }
        artifact_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('model_artifacts')")
        }
    finally:
        connection.close()
        get_settings.cache_clear()

    assert "experiments" in tables
    assert "training_runs" in tables
    assert "model_artifacts" in tables
    assert "ix_experiments_name" in experiment_indexes
    assert "ix_training_runs_experiment_status" in run_indexes
    assert "ix_model_artifacts_training_run_version" in artifact_indexes

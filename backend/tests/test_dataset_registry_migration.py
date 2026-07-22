"""Dataset Registry and training-lineage migration round trip."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_dataset_registry_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "dataset-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-sufficient-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "0013_integrate_dataset_training")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        training_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('training_jobs')")
        }
        automl_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('automl_studies')")
        }
    assert {
        "datasets",
        "dataset_versions",
        "document_records",
        "document_chunks",
        "dataset_usage_references",
    } <= tables
    assert "dataset_version_id" in training_columns
    assert "dataset_version_id" in automl_columns

    command.downgrade(config, "0011_adjust_automl_trial_uniqueness")
    with sqlite3.connect(path) as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "datasets" not in remaining
    assert "automl_studies" in remaining
    command.upgrade(config, "0013_integrate_dataset_training")
    get_settings.cache_clear()

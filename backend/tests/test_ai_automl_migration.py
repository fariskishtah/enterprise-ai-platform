"""AutoML Alembic upgrade, downgrade, and repeat-upgrade validation."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_automl_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "automl-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-sufficient-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('automl_trials')")
        }
    assert {"automl_studies", "automl_trials", "automl_execution_slots"} <= tables
    assert "ix_automl_trials_study_status" in indexes

    command.downgrade(config, "0009_add_monitoring_orchestration")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "automl_studies" not in tables
    assert "monitoring_alerts" in tables
    command.upgrade(config, "head")
    get_settings.cache_clear()

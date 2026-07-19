"""Prediction-monitoring Alembic upgrade and downgrade tests."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_prediction_monitoring_migration_upgrade_and_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revision creates bounded-query indexes, checks, and version uniqueness."""
    database_path = tmp_path / "ai-monitoring-migration.db"
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
        event_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list('prediction_events')")
        }
        profile_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('model_reference_profiles')",
            )
        }
        event_definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='prediction_events'",
        ).fetchone()[0]
    finally:
        connection.close()

    assert {"prediction_events", "model_reference_profiles"} <= tables
    assert "ix_prediction_events_model_window" in event_indexes
    assert "ix_prediction_events_requested_by" in event_indexes
    assert "ix_model_reference_profiles_model_version" in profile_indexes
    assert "duration_ms >= 0" in event_definition
    assert "status != 'succeeded' OR row_count > 0" in event_definition

    command.downgrade(config, "0006_add_ai_jobs_and_promotion")
    connection = sqlite3.connect(database_path)
    try:
        downgraded_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
    finally:
        connection.close()
        get_settings.cache_clear()

    assert "prediction_events" not in downgraded_tables
    assert "model_reference_profiles" not in downgraded_tables
    assert "training_jobs" in downgraded_tables

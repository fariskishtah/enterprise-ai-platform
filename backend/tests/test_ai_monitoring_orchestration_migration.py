"""Monitoring orchestration Alembic upgrade and downgrade coverage."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_monitoring_orchestration_migration_is_reversible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "monitoring-orchestration.db"
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
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        evaluation_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('model_monitoring_evaluations')"
            )
        }
        alert_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list('monitoring_alerts')")
        }
        request_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('model_retraining_requests')"
            )
        }
    finally:
        connection.close()

    assert {
        "model_monitoring_evaluations",
        "monitoring_alerts",
        "monitoring_job_locks",
        "prediction_outcomes",
    } <= tables
    assert "ix_monitoring_evaluation_model_version_time" in evaluation_indexes
    assert "ix_monitoring_alert_model_status" in alert_indexes
    assert "monitoring_evaluation_id" in request_columns

    command.downgrade(config, "0008_add_controlled_retraining")
    connection = sqlite3.connect(database_path)
    try:
        downgraded = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        request_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('model_retraining_requests')"
            )
        }
    finally:
        connection.close()
        get_settings.cache_clear()

    assert "model_monitoring_evaluations" not in downgraded
    assert "monitoring_alerts" not in downgraded
    assert "prediction_outcomes" not in downgraded
    assert "monitoring_evaluation_id" not in request_columns

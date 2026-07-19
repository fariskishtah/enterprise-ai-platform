"""Controlled retraining Alembic upgrade and downgrade tests."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_retraining_migration_upgrade_and_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "ai-retraining-migration.db"
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
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        policy_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('model_retraining_policies')"
            )
        }
        request_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('model_retraining_requests')"
            )
        }
        audit_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('model_retraining_audits')"
            )
        }
        policy_definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='model_retraining_policies'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert {
        "model_retraining_policies",
        "model_retraining_requests",
        "model_retraining_audits",
    } <= tables
    assert "ix_retraining_policy_enabled" in policy_indexes
    assert "ix_retraining_request_model_status" in request_indexes
    assert "ix_retraining_audit_evaluated_at" in audit_indexes
    assert "cooldown_seconds >= 0" in policy_definition
    assert "maximum_active_requests > 0" in policy_definition

    command.downgrade(config, "0007_add_ai_prediction_monitoring")
    connection = sqlite3.connect(database_path)
    try:
        downgraded = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
        get_settings.cache_clear()

    assert "model_retraining_policies" not in downgraded
    assert "model_retraining_requests" not in downgraded
    assert "model_retraining_audits" not in downgraded
    assert "prediction_events" in downgraded

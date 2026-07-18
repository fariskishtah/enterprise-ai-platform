"""Background-job and promotion-audit Alembic migration tests."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_ai_governance_migration_upgrade_and_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new revision creates its indexes and cleanly downgrades one step."""
    database_path = tmp_path / "ai-governance-migration.db"
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
        job_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('training_jobs')")
        }
        audit_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('model_promotion_audits')",
            )
        }
    finally:
        connection.close()

    assert {"training_jobs", "model_promotion_audits"} <= tables
    assert "ix_training_jobs_queue_message_id" in job_indexes
    assert "ix_training_jobs_status_started_at" in job_indexes
    assert "ix_model_promotion_audits_model_name" in audit_indexes

    command.downgrade(config, "0005_create_mlops_foundation")
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

    assert "training_jobs" not in downgraded_tables
    assert "model_promotion_audits" not in downgraded_tables
    assert "training_runs" in downgraded_tables

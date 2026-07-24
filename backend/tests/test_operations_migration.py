"""Operational workflow migration upgrade and downgrade coverage."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_operations_migrations_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "operations-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "operations-migration-secret-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "0015_add_pilot_identity_audit")
    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "operational_actions",
            "operational_notes",
            "maintenance_feedback",
            "operational_timeline_events",
            "shift_handovers",
        } <= tables

        alert_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(monitoring_alerts)")
        }
        assert {
            "assigned_user_id",
            "assigned_at",
            "in_progress_at",
            "escalated_at",
            "resolution_summary",
            "resolution_classification",
            "reopened_at",
            "reopen_reason",
            "lifecycle_version",
        } <= alert_columns

        action_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(operational_actions)")
        }
        assert {
            "ix_operational_actions_company_status",
            "ix_operational_actions_factory_status",
            "ix_operational_actions_machine_status",
            "ix_operational_actions_assignee_status",
            "ix_operational_actions_company_title",
            "ix_operational_actions_priority_due",
        } <= action_indexes

        shift_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(shift_handovers)")
        }
        assert "uq_shift_handovers_active_factory" in shift_indexes

    command.downgrade(config, "0015_add_pilot_identity_audit")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "operational_actions" not in tables
        assert "shift_handovers" not in tables
        alert_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(monitoring_alerts)")
        }
        assert "assigned_user_id" not in alert_columns
        assert "lifecycle_version" not in alert_columns

    command.upgrade(config, "head")
    command.check(config)
    get_settings.cache_clear()

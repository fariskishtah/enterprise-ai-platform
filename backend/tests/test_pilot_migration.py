"""Tenant, identity, audit, and pilot migration round-trip coverage."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_pilot_migration_backfills_legacy_users_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pilot-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "pilot-migration-secret-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "0014_add_secure_rag_chat")
    company_id = uuid4().hex
    user_id = uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO companies (id, name, normalized_name) VALUES (?, ?, ?)",
            (company_id, "Legacy Pilot Company", "legacy pilot company"),
        )
        connection.execute(
            "INSERT INTO users "
            "(id, email, hashed_password, role, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                "legacy-pilot@example.invalid",
                "not-a-real-password-hash",
                "admin",
                True,
            ),
        )
        connection.commit()

    command.upgrade(config, "0015_add_pilot_identity_audit")

    with sqlite3.connect(database_path) as connection:
        backfilled_company_id = connection.execute(
            "SELECT company_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert backfilled_company_id == (company_id,)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "audit_events",
            "password_reset_tokens",
            "model_feature_schemas",
            "machine_risk_assessments",
        } <= tables
        user_columns = {
            row[1]: row[3] for row in connection.execute("PRAGMA table_info(users)")
        }
        assert user_columns["company_id"] == 1
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(model_reference_profiles)")
        }
        assert "ix_model_reference_profiles_model_version" in indexes
        prediction_table_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'prediction_events'"
        ).fetchone()
        assert prediction_table_sql is not None
        assert "'ridge'" in prediction_table_sql[0]

    command.downgrade(config, "0014_add_secure_rag_chat")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "audit_events" not in tables
        user_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)")
        }
        assert "company_id" not in user_columns

    command.upgrade(config, "head")
    command.check(config)
    get_settings.cache_clear()

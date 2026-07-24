"""Support request migration upgrade, constraint, and downgrade coverage."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_support_request_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "support-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "support-migration-secret-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "0020_add_executive_reports")
    company_id = uuid4().hex
    user_id = uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO companies (id, name, normalized_name) VALUES (?, ?, ?)",
            (company_id, "Support Company", "support company"),
        )
        connection.execute(
            "INSERT INTO users "
            "(id, email, company_id, hashed_password, role, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                "support-migration@example.invalid",
                company_id,
                "not-a-real-password-hash",
                "admin",
                True,
            ),
        )
        connection.commit()

    command.upgrade(config, "0021_add_support_requests")

    request_id = uuid4().hex
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        assert "full_name" in columns
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(support_requests)")
        }
        assert {
            "uq_support_request_actor_idempotency",
            "ix_support_request_company_created",
            "ix_support_request_company_status",
        } <= indexes
        values = (
            request_id,
            company_id,
            user_id,
            "Support User",
            "support-migration@example.invalid",
            "admin",
            "Support Company",
            "technical_problem",
            "Migration request",
            "Verify support schema constraints.",
            "/settings",
            "submitted",
            "support:migration",
            0,
        )
        connection.execute(
            "INSERT INTO support_requests "
            "(id, company_id, created_by, requester_name, requester_email, "
            "requester_role, company_name, category, subject, message, current_page, "
            "status, idempotency_key, delivery_attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO support_requests "
                "(id, company_id, created_by, requester_name, requester_email, "
                "requester_role, company_name, category, subject, message, "
                "current_page, status, idempotency_key, delivery_attempts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid4().hex, *values[1:]),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE support_requests SET delivery_attempts = 6 WHERE id = ?",
                (request_id,),
            )
        connection.rollback()

    command.downgrade(config, "0020_add_executive_reports")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "support_requests" not in tables
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        assert "full_name" not in columns

    command.upgrade(config, "head")
    command.check(config)
    get_settings.cache_clear()

"""Email verification migration and existing-account backfill coverage."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_email_verification_migration_backfills_existing_users(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "email-verification-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "verification-migration-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "0024_add_transactional_email")
    company_id = uuid4().hex
    user_id = uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO companies (id, name, normalized_name) VALUES (?, ?, ?)",
            (company_id, "Verification Existing", "verification existing"),
        )
        connection.execute(
            "INSERT INTO users "
            "(id, email, company_id, hashed_password, role, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                "existing-verification@example.com",
                company_id,
                "not-a-password-hash",
                "admin",
                True,
            ),
        )
        connection.commit()

    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(database_path) as connection:
        verified, verified_at = connection.execute(
            "SELECT is_email_verified, email_verified_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        email_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(outbound_email_messages)")
        }
    assert verified == 1
    assert verified_at is not None
    assert "email_verification_tokens" in tables
    assert "payload_encrypted" in email_columns

    command.downgrade(config, "0024_add_transactional_email")
    with sqlite3.connect(database_path) as connection:
        user_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)")
        }
    assert "is_email_verified" not in user_columns
    get_settings.cache_clear()

"""Transactional email migration upgrade and downgrade coverage."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_transactional_email_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "transactional-email-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "email-migration-test-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(outbound_email_messages)")
        }
    assert "outbound_email_messages" in tables
    assert {
        "ix_outbound_email_status_next",
        "ix_outbound_email_company_created",
    } <= indexes
    assert any(
        name.startswith("sqlite_autoindex_outbound_email_messages") for name in indexes
    )

    command.downgrade(config, "0023_add_billing_foundation")
    with sqlite3.connect(database_path) as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "outbound_email_messages" not in remaining
    assert "billing_plans" in remaining
    get_settings.cache_clear()

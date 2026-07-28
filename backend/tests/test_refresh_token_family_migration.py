"""Refresh-token family migration round-trip coverage."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_refresh_token_family_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "refresh-token-family.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "refresh-family-migration-secret-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(refresh_tokens)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(refresh_tokens)")
        }
    assert {"family_id", "parent_token_id"} <= columns
    assert "ix_refresh_tokens_family_id" in indexes

    command.downgrade(config, "0027_add_team_invitations")
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(refresh_tokens)")
        }
    assert "family_id" not in columns
    assert "parent_token_id" not in columns
    get_settings.cache_clear()

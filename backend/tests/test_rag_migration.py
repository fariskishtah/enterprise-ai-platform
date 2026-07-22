"""RAG and grounded-chat persistence migration round trip."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_rag_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rag-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-sufficient-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list('rag_chunk_embeddings')")
        }
    assert {
        "rag_knowledge_bases",
        "rag_knowledge_base_dataset_versions",
        "rag_index_builds",
        "rag_indexed_chunks",
        "rag_chunk_embeddings",
        "rag_conversations",
        "rag_messages",
        "rag_message_citations",
    } <= tables
    assert "ix_rag_chunk_embeddings_scope" in indexes

    command.downgrade(config, "0013_integrate_dataset_training")
    with sqlite3.connect(path) as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "rag_knowledge_bases" not in remaining
    assert "datasets" in remaining
    command.upgrade(config, "head")
    get_settings.cache_clear()

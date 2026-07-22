"""Static safety contracts for local backup and disaster recovery tooling."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, cast

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_BACKUP_SCRIPT = _ROOT / "scripts/backup-postgres.sh"
_VERIFY_SCRIPT = _ROOT / "scripts/verify-postgres-backup.sh"
_COMPOSE = _ROOT / "docker-compose.yml"
_RUNBOOK = _ROOT / "docs/backups-and-disaster-recovery.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _yaml(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(_text(path)))


def test_backup_scripts_are_executable_and_use_strict_bash() -> None:
    for script in (_BACKUP_SCRIPT, _VERIFY_SCRIPT):
        assert script.is_file()
        assert script.stat().st_mode & stat.S_IXUSR
        assert _text(script).startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")


def test_backup_retention_is_bounded_to_matching_files_in_backup_directory() -> None:
    script = _text(_BACKUP_SCRIPT)

    assert 'find "$BACKUP_DIR" -maxdepth 1 -type f' in script
    assert "-name 'postgres-*.dump'" in script
    assert "-name 'postgres-*.dump.sha256'" in script
    assert "-name 'dataset-*.tar.gz'" in script
    assert "-name 'dataset-*.tar.gz.sha256'" in script
    assert "dst=/source,readonly" in script
    assert "--network none" in script
    assert 'rm -f -- "$expired_file"' in script
    assert "docker volume" not in script


def test_verification_uses_an_ephemeral_container_not_the_live_database() -> None:
    script = _text(_VERIFY_SCRIPT)

    assert "docker run --detach --rm" in script
    assert "docker compose exec" not in script
    assert "postgres-data" not in script
    assert "pg_restore" in script
    assert "information_schema.tables" in script
    assert "tar -tzf" in script
    assert "pg_extension" in script


def test_compose_keeps_redis_aof_persistence_on_the_existing_volume() -> None:
    redis = _yaml(_COMPOSE)["services"]["redis"]

    assert redis["command"] == [
        "redis-server",
        "--appendonly",
        "yes",
        "--appendfsync",
        "everysec",
    ]
    assert redis["volumes"] == ["redis-data:/data"]
    assert redis["ports"] == ["127.0.0.1:${REDIS_PORT:-6379}:6379"]


def test_runbook_defines_recovery_targets_and_restore_verification() -> None:
    runbook = _text(_RUNBOOK).lower()

    assert "rpo" in runbook
    assert "rto" in runbook
    assert "./scripts/verify-postgres-backup.sh" in runbook
    assert "never restores into the live" in runbook
    assert "dataset archive" in runbook

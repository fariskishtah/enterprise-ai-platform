"""Six-role policy, migration, and tenant administration coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import Settings, get_settings
from app.models.user import UserRole
from app.permissions import ROLE_PERMISSIONS, Permission, has_permissions
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers


def test_explicit_permission_matrix_covers_exactly_six_roles() -> None:
    assert set(ROLE_PERMISSIONS) == set(UserRole)
    assert len(UserRole) == 6
    assert has_permissions(UserRole.OWNER, *Permission)
    assert has_permissions(UserRole.ADMIN, Permission.TEAM_MANAGE)
    assert not has_permissions(UserRole.ADMIN, Permission.OWNER_ASSIGN)
    assert has_permissions(UserRole.ENGINEER, Permission.ENGINEERING_WRITE)
    assert has_permissions(UserRole.OPERATOR, Permission.OPERATIONS_EXECUTE)
    assert has_permissions(UserRole.ANALYST, Permission.ENGINEERING_READ)
    assert not has_permissions(UserRole.ANALYST, Permission.ENGINEERING_WRITE)
    assert has_permissions(UserRole.VIEWER, Permission.PLATFORM_READ)
    assert not has_permissions(UserRole.VIEWER, Permission.OPERATIONS_EXECUTE)


@pytest.mark.anyio
async def test_owner_admin_privilege_boundaries_and_last_owner_protection(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="rbac-owner@example.com",
        )
        admin = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="rbac-admin@example.com",
        )
        admin_me = await client.get("/users/me", headers=admin)
        promote_self = await client.patch(
            f"/users/{admin_me.json()['id']}", headers=admin, json={"role": "owner"}
        )
        assert promote_self.status_code == 409

        owner_me = await client.get("/users/me", headers=owner)
        remove_last_owner = await client.patch(
            f"/users/{owner_me.json()['id']}",
            headers=owner,
            json={"role": "admin"},
        )
        assert remove_last_owner.status_code == 409

        analyst = await client.post(
            "/users",
            headers=owner,
            json={
                "email": "rbac-analyst@example.com",
                "password": "SixRolePassword1!",
                "role": "analyst",
            },
        )
        assert analyst.status_code == 201
        viewer_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.VIEWER,
            email="rbac-viewer@example.com",
        )
        assert (
            await client.get("/factories", headers=viewer_headers)
        ).status_code == 200
        assert (
            await client.post(
                "/factories", headers=viewer_headers, json={"name": "Denied"}
            )
        ).status_code == 403


def test_six_role_migration_backfills_admin_to_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "six-role.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "six-role-migration-secret-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "0025_add_email_verification")
    company_id, user_id = uuid4().hex, uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO companies (id, name, normalized_name) VALUES (?, ?, ?)",
            (company_id, "Six Role", "six role"),
        )
        connection.execute(
            "INSERT INTO users "
            "(id, email, company_id, hashed_password, role, is_active) "
            "VALUES (?, ?, ?, ?, 'admin', true)",
            (user_id, "owner@example.com", company_id, "not-a-hash"),
        )
        connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(database_path) as connection:
        role = connection.execute(
            "SELECT role FROM users WHERE id = ?", (user_id,)
        ).fetchone()[0]
    assert role == "owner"
    command.downgrade(config, "0025_add_email_verification")
    with sqlite3.connect(database_path) as connection:
        role = connection.execute(
            "SELECT role FROM users WHERE id = ?", (user_id,)
        ).fetchone()[0]
    assert role == "admin"
    get_settings.cache_clear()

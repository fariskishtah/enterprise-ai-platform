"""Team invitation lifecycle, tenant boundary, and delivery coverage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import Settings, get_settings
from app.dependencies.services import get_transactional_email_queue
from app.models.email import OutboundEmailMessage
from app.models.manufacturing import Company
from app.models.user import TeamInvitation, UserRole
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from app.utils.security import utc_now
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers

PASSWORD = "InvitationPassword1!"


@dataclass
class RecordingQueue:
    ids: list[UUID] = field(default_factory=list)

    def enqueue(self, message_id: UUID) -> str:
        self.ids.append(message_id)
        return str(message_id)


def invitation_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "email_provider": "capture",
            "email_from": "team@example.com",
            "expose_local_team_invitation_token": True,
            "team_invitation_expire_hours": 72,
            "team_invitation_resend_cooldown_seconds": 60,
        }
    )


async def invite(client, headers, *, email: str, role: str = "engineer"):
    return await client.post(
        "/team/invitations",
        headers=headers,
        json={"email": email, "role": role},
    )


@pytest.mark.anyio
async def test_new_user_invitation_is_private_delivered_and_single_use(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    queue = RecordingQueue()
    async with ai_api_client(
        invitation_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="invite-owner@example.com",
        )
        created = await invite(
            client, owner, email="new-invitee@example.com", role="engineer"
        )
        duplicate = await invite(
            client, owner, email="new-invitee@example.com", role="viewer"
        )
        assert created.status_code == 201, created.text
        assert duplicate.status_code == 409
        token = created.json()["local_invitation_token"]
        invitation_id = UUID(created.json()["id"])
        assert isinstance(token, str)

        accepted = await client.post(
            "/team/invitations/accept",
            json={
                "token": token,
                "full_name": "New Invitee",
                "password": PASSWORD,
            },
        )
        reused = await client.post("/team/invitations/accept", json={"token": token})
        login = await client.post(
            "/auth/login",
            json={"email": "new-invitee@example.com", "password": PASSWORD},
        )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["user"]["role"] == "engineer"
    assert accepted.json()["user"]["is_email_verified"] is True
    assert reused.status_code == 409
    assert login.status_code == 200
    assert len(queue.ids) == 1
    async with session_factory() as session:
        invitation = await session.get(TeamInvitation, invitation_id)
        message = await session.get(OutboundEmailMessage, queue.ids[0])
    assert invitation is not None and invitation.token_hash != token
    assert invitation.accepted_at is not None
    assert message is not None and message.payload_encrypted is True
    assert token not in message.text_body and token not in message.html_body


@pytest.mark.anyio
async def test_existing_user_acceptance_resend_cooldown_and_revocation(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    queue = RecordingQueue()
    async with ai_api_client(
        invitation_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="existing-owner@example.com",
        )
        existing = await auth_headers(
            client,
            session_factory,
            role=UserRole.VIEWER,
            email="existing-invitee@example.com",
        )
        del existing
        created = await invite(
            client, owner, email="existing-invitee@example.com", role="analyst"
        )
        invitation_id = created.json()["id"]
        cooldown = await client.post(
            f"/team/invitations/{invitation_id}/resend", headers=owner
        )
        assert cooldown.status_code == 429
        async with session_factory() as session:
            invitation = await session.get(TeamInvitation, UUID(invitation_id))
            assert invitation is not None
            invitation.last_sent_at = utc_now() - timedelta(seconds=61)
            await session.commit()
        resent = await client.post(
            f"/team/invitations/{invitation_id}/resend", headers=owner
        )
        assert resent.status_code == 200, resent.text
        new_token = resent.json()["local_invitation_token"]
        accepted = await client.post(
            "/team/invitations/accept", json={"token": new_token}
        )
        assert accepted.status_code == 200
        assert accepted.json()["user"]["role"] == "analyst"

        revoked_invite = await invite(
            client, owner, email="revoked@example.com", role="viewer"
        )
        revoked_token = revoked_invite.json()["local_invitation_token"]
        revoked = await client.delete(
            f"/team/invitations/{revoked_invite.json()['id']}", headers=owner
        )
        rejected = await client.post(
            "/team/invitations/accept", json={"token": revoked_token}
        )
    assert revoked.status_code == 204
    assert rejected.status_code == 409
    assert len(queue.ids) == 3


@pytest.mark.anyio
async def test_invitation_privilege_and_tenant_boundaries(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(
        invitation_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, _application):
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.OWNER,
            email="boundary-owner@example.com",
        )
        admin = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="boundary-admin@example.com",
        )
        owner_escalation = await invite(
            client, admin, email="another-owner@example.com", role="owner"
        )
        assert owner_escalation.status_code == 409
        owner_demotion = await invite(
            client, admin, email="boundary-owner@example.com", role="analyst"
        )
        assert owner_demotion.status_code == 201
        blocked_demotion = await client.post(
            "/team/invitations/accept",
            json={"token": owner_demotion.json()["local_invitation_token"]},
        )
        assert blocked_demotion.status_code == 409
        invalid_role = await invite(
            client, owner, email="invalid-role@example.com", role="superadmin"
        )
        assert invalid_role.status_code == 422
        created = await invite(
            client, owner, email="tenant-bound@example.com", role="viewer"
        )
        pending = await client.get("/team/invitations", headers=owner)
        assert pending.status_code == 200
        assert created.json()["id"] in {item["id"] for item in pending.json()["items"]}

        expired_invite = await invite(
            client, owner, email="expired-invite@example.com", role="viewer"
        )
        async with session_factory() as session:
            expired_entity = await session.get(
                TeamInvitation, UUID(expired_invite.json()["id"])
            )
            assert expired_entity is not None
            expired_entity.expires_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        expired = await client.post(
            "/team/invitations/accept",
            json={"token": expired_invite.json()["local_invitation_token"]},
        )
        assert expired.status_code == 410

        async with session_factory() as session:
            company = Company(
                name="Invitation Other Tenant",
                normalized_name="invitation other tenant",
            )
            session.add(company)
            await session.flush()
            other = await UserService(
                repository=UserRepository(session), password_hasher=PasswordHasher()
            ).create_user(
                email="other-invite-owner@example.com",
                password=PASSWORD,
                role=UserRole.OWNER,
                company_id=company.id,
            )
            other_company_id = other.company_id
        other_login = await client.post(
            "/auth/login",
            json={"email": "other-invite-owner@example.com", "password": PASSWORD},
        )
        other_headers = {
            "Authorization": f"Bearer {other_login.json()['access_token']}"
        }
        hidden = await client.delete(
            f"/team/invitations/{created.json()['id']}", headers=other_headers
        )
        assert hidden.status_code == 404

        cross = await invite(
            client, owner, email="other-invite-owner@example.com", role="analyst"
        )
        rejected = await client.post(
            "/team/invitations/accept",
            json={"token": cross.json()["local_invitation_token"]},
        )
    assert rejected.status_code == 409
    assert str(other_company_id) not in rejected.text


def test_team_invitation_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "team-invitations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "invitation-migration-secret-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(team_invitations)")
        }
    assert {"token_hash", "accepted_at", "revoked_at", "last_sent_at"} <= columns
    command.downgrade(config, "0026_add_six_role_rbac")
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "team_invitations" not in tables
    get_settings.cache_clear()

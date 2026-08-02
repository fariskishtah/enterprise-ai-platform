"""Email verification lifecycle, enforcement, and captured delivery coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.dependencies.services import get_transactional_email_queue
from app.models.email import OutboundEmailMessage
from app.models.user import AuditEvent, EmailVerificationToken, User
from app.services.email import CaptureEmailProvider
from app.services.email_delivery import EmailDeliveryWorker, EmailWorkerState
from app.utils.security import utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client

PASSWORD = "VerificationPassword1!"


@dataclass
class RecordingQueue:
    message_ids: list[UUID] = field(default_factory=list)

    def enqueue(self, message_id: UUID) -> str:
        self.message_ids.append(message_id)
        return f"verification-{len(self.message_ids)}"


def verification_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "app_base_url": "http://localhost:5173",
            "email_provider": "capture",
            "email_from": "accounts@example.com",
            "email_verification_required": True,
            "email_verification_expire_hours": 24,
            "email_verification_resend_cooldown_seconds": 60,
            "expose_local_email_verification_token": True,
        }
    )


async def register(client, *, email: str = "verify@example.com"):
    return await client.post(
        "/auth/register",
        json={
            "company_name": f"Verification Company {email}",
            "email": email,
            "name": "Verification User",
            "password": PASSWORD,
        },
    )


async def login_headers(client, *, email: str = "verify@example.com") -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.anyio
async def test_new_account_is_unverified_and_captured_payload_is_encrypted(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    configured = verification_settings(settings)
    queue = RecordingQueue()
    async with ai_api_client(configured, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        response = await register(client)

    assert response.status_code == 201
    body = response.json()
    token = body["local_verification_token"]
    assert body["is_email_verified"] is False
    assert isinstance(token, str)
    assert len(queue.message_ids) == 1
    async with session_factory() as session:
        user = await session.get(User, UUID(body["id"]))
        token_row = await session.scalar(select(EmailVerificationToken))
        message = await session.get(OutboundEmailMessage, queue.message_ids[0])
    assert user is not None and user.email_verified_at is None
    assert token_row is not None and token_row.token_hash != token
    assert message is not None and message.payload_encrypted is True
    assert token not in message.text_body
    assert token not in message.html_body

    provider = CaptureEmailProvider()
    outcome = await EmailDeliveryWorker(
        session_factory=session_factory,
        provider=provider,
        retry_base_seconds=1,
        payload_encryption_key=configured.secret_key.get_secret_value(),
    ).execute(queue.message_ids[0])
    assert outcome is EmailWorkerState.CAPTURED
    assert token in provider.messages[0].html


@pytest.mark.anyio
async def test_verification_success_reuse_status_and_server_enforcement(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    configured = verification_settings(settings)
    queue = RecordingQueue()
    async with ai_api_client(configured, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        created = await register(client, email="enforced@example.com")
        token = created.json()["local_verification_token"]
        headers = await login_headers(client, email="enforced@example.com")
        me = await client.get("/users/me", headers=headers)
        blocked = await client.get("/users", headers=headers)
        verified = await client.post(
            "/auth/email-verification/verify", json={"token": token}
        )
        reused = await client.post(
            "/auth/email-verification/verify", json={"token": token}
        )
        allowed = await client.get("/users", headers=headers)
        status_response = await client.get(
            "/auth/email-verification/status", headers=headers
        )

    assert me.status_code == 200
    assert blocked.status_code == 403
    assert "verification" in blocked.json()["detail"].lower()
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert reused.status_code == 409
    assert allowed.status_code == 200
    assert status_response.json()["is_verified"] is True
    assert len(queue.message_ids) == 2  # verification plus welcome
    async with session_factory() as session:
        user = await session.scalar(
            select(User).where(User.email == "enforced@example.com")
        )
        action = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "email.verified")
        )
    assert user is not None and user.email_verified_at is not None
    assert action is not None


@pytest.mark.anyio
async def test_invalid_expired_and_resend_cooldown_states(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    configured = verification_settings(settings)
    queue = RecordingQueue()
    async with ai_api_client(configured, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        created = await register(client, email="expired@example.com")
        token = created.json()["local_verification_token"]
        headers = await login_headers(client, email="expired@example.com")
        invalid = await client.post(
            "/auth/email-verification/verify", json={"token": "x" * 48}
        )
        resend = await client.post("/auth/email-verification/resend", headers=headers)
        status_response = await client.get(
            "/auth/email-verification/status", headers=headers
        )
        async with session_factory() as session:
            token_row = await session.scalar(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.token_hash.is_not(None)
                )
            )
            assert token_row is not None
            token_row.expires_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        expired = await client.post(
            "/auth/email-verification/verify", json={"token": token}
        )

    assert invalid.status_code == 422
    assert resend.status_code == 200
    assert resend.json()["local_verification_token"] is None
    assert resend.json()["resend_available_in_seconds"] > 0
    assert status_response.json()["resend_available_in_seconds"] > 0
    assert len(queue.message_ids) == 1
    assert expired.status_code == 410


@pytest.mark.anyio
async def test_duplicate_registration_remains_confidentially_rejected(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    queue = RecordingQueue()
    async with ai_api_client(
        verification_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        first = await register(client, email="duplicate-verify@example.com")
        duplicate = await register(client, email="duplicate-verify@example.com")
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert len(queue.message_ids) == 1


@pytest.mark.anyio
async def test_already_verified_token_state_is_distinct(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    queue = RecordingQueue()
    async with ai_api_client(
        verification_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        created = await register(client, email="already-verified@example.com")
        token = created.json()["local_verification_token"]
        async with session_factory() as session:
            user = await session.scalar(
                select(User).where(User.email == "already-verified@example.com")
            )
            assert user is not None
            user.is_email_verified = True
            user.email_verified_at = utc_now()
            await session.commit()
        response = await client.post(
            "/auth/email-verification/verify", json={"token": token}
        )

    assert response.status_code == 200
    assert response.json()["status"] == "already_verified"
    assert len(queue.message_ids) == 1  # no duplicate welcome message


@pytest.mark.anyio
async def test_password_reset_uses_private_durable_email_and_generic_response(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    configured = verification_settings(settings).model_copy(
        update={"expose_local_password_reset_token": True}
    )
    queue = RecordingQueue()
    async with ai_api_client(configured, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_transactional_email_queue] = lambda: queue
        await register(client, email="reset-delivery@example.com")
        known = await client.post(
            "/auth/password-reset/request",
            json={"email": "reset-delivery@example.com"},
        )
        duplicate = await client.post(
            "/auth/password-reset/request",
            json={"email": "reset-delivery@example.com"},
        )
        unknown = await client.post(
            "/auth/password-reset/request",
            json={"email": "unknown-reset@example.com"},
        )

    assert known.status_code == unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]
    raw_token = known.json()["local_reset_token"]
    assert isinstance(raw_token, str)
    assert duplicate.status_code == 200
    assert duplicate.json()["message"] == known.json()["message"]
    assert duplicate.json()["local_reset_token"] is None
    assert unknown.json()["local_reset_token"] is None
    assert len(queue.message_ids) == 2  # registration verification plus known reset
    async with session_factory() as session:
        message = await session.scalar(
            select(OutboundEmailMessage).where(
                OutboundEmailMessage.message_type == "password_reset"
            )
        )
    assert message is not None and message.payload_encrypted is True
    assert raw_token not in message.text_body
    assert raw_token not in message.html_body

    provider = CaptureEmailProvider()
    result = await EmailDeliveryWorker(
        session_factory=session_factory,
        provider=provider,
        retry_base_seconds=1,
        payload_encryption_key=configured.secret_key.get_secret_value(),
    ).execute(message.id)
    assert result is EmailWorkerState.CAPTURED
    assert raw_token in provider.messages[0].html
    assert "30 minutes" in provider.messages[0].text
    assert "Security note:" in provider.messages[0].text

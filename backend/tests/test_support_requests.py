"""Focused tests for authenticated, tenant-scoped support delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from app.config.settings import Settings
from app.dependencies.rate_limit import get_auth_rate_limit_store
from app.dependencies.services import get_support_email_provider
from app.models.manufacturing import Company, Factory, Machine
from app.models.support import SupportRequest
from app.models.user import AuditEvent, UserRole
from app.services.email import (
    EmailDeliveryError,
    EmailDeliveryResult,
    OutboundEmail,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers


@dataclass
class RecordingEmailProvider:
    """Record bounded messages while allowing deterministic provider failure."""

    fail: bool = False
    messages: list[OutboundEmail] = field(default_factory=list)

    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        self.messages.append(message)
        if self.fail:
            raise EmailDeliveryError("Synthetic provider failure.")
        return EmailDeliveryResult(provider_message_id=f"test-{len(self.messages)}")


@dataclass
class CountingRateLimitStore:
    counts: dict[str, int] = field(default_factory=dict)

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key], window_seconds


def support_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "email_from": "support@verified.example",
            "support_email_to": "destination@example.test",
            "support_email_max_attempts": 3,
        }
    )


def support_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "category": "technical_problem",
        "subject": "Factory dashboard issue",
        "message": "The dashboard did not refresh after the latest sensor reading.",
        "current_page": "/factories",
        "idempotency_key": f"support:{uuid4()}",
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
async def test_support_request_is_delivered_escaped_idempotent_and_audited(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    provider = RecordingEmailProvider()
    async with ai_api_client(
        support_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_support_email_provider] = lambda: provider
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="support-engineer@example.com",
        )
        payload = support_payload(
            subject="Escaped <subject>",
            message="Unexpected value <script>alert('no')</script> on the dashboard.",
        )

        response = await client.post("/support/requests", json=payload, headers=headers)
        duplicate = await client.post(
            "/support/requests", json=payload, headers=headers
        )

    assert response.status_code == 201
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == response.json()["id"]
    assert response.json()["status"] == "delivered"
    assert response.json()["delivery_attempts"] == 1
    assert len(provider.messages) == 1
    delivered = provider.messages[0]
    assert delivered.to == "destination@example.test"
    assert delivered.from_address == "support@verified.example"
    assert delivered.reply_to == "support-engineer@example.com"
    assert "<script>" not in delivered.html
    assert "&lt;script&gt;" in delivered.html

    async with session_factory() as session:
        request_id = UUID(response.json()["id"])
        item = await session.scalar(
            select(SupportRequest).where(SupportRequest.id == request_id)
        )
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == response.json()["id"],
                AuditEvent.action == "support.request_submitted",
            )
        )
    assert item is not None
    assert item.last_error is None
    assert event is not None
    assert event.safe_metadata == {
        "category": "technical_problem",
        "delivery_status": "delivered",
        "delivery_attempts": 1,
    }


@pytest.mark.anyio
async def test_failed_delivery_is_persisted_and_admin_can_retry(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    provider = RecordingEmailProvider(fail=True)
    async with ai_api_client(
        support_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_support_email_provider] = lambda: provider
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="support-admin@example.com",
        )
        create = await client.post(
            "/support/requests",
            json=support_payload(),
            headers=admin_headers,
        )
        assert create.status_code == 201
        assert create.json()["status"] == "delivery_failed"
        assert "saved" in create.json()["delivery_message"].lower()
        assert "failed" in create.json()["delivery_message"].lower()
        assert "Synthetic provider failure" not in create.text

        provider.fail = False
        resent = await client.post(
            f"/support/requests/{create.json()['id']}/resend",
            headers=admin_headers,
        )
        listed = await client.get("/support/requests", headers=admin_headers)

    assert resent.status_code == 200
    assert resent.json()["status"] == "delivered"
    assert resent.json()["delivery_attempts"] == 2
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == create.json()["id"]
    assert len(provider.messages) == 2

    async with session_factory() as session:
        request_id = UUID(create.json()["id"])
        item = await session.scalar(
            select(SupportRequest).where(SupportRequest.id == request_id)
        )
        actions = list(
            await session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.resource_id == create.json()["id"]
                )
            )
        )
    assert item is not None
    assert item.last_error is None
    assert actions == ["support.request_submitted", "support.request_resent"]


@pytest.mark.anyio
async def test_support_rejects_invalid_and_cross_tenant_context(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    other_company_id = uuid4()
    other_factory_id = uuid4()
    other_machine_id = uuid4()
    async with session_factory() as session:
        session.add(
            Company(
                id=other_company_id,
                name="Other tenant",
                normalized_name=f"other-tenant-{other_company_id}",
            )
        )
        session.add(
            Factory(
                id=other_factory_id,
                company_id=other_company_id,
                name="Other factory",
            )
        )
        session.add(
            Machine(
                id=other_machine_id,
                factory_id=other_factory_id,
                name="Other machine",
            )
        )
        await session.commit()

    provider = RecordingEmailProvider()
    async with ai_api_client(
        support_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_support_email_provider] = lambda: provider
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="support-operator@example.com",
        )
        unauthenticated = await client.post("/support/requests", json=support_payload())
        invalid = await client.post(
            "/support/requests",
            json=support_payload(current_page="https://outside.example"),
            headers=headers,
        )
        cross_factory = await client.post(
            "/support/requests",
            json=support_payload(factory_id=str(other_factory_id)),
            headers=headers,
        )
        cross_machine = await client.post(
            "/support/requests",
            json=support_payload(machine_id=str(other_machine_id)),
            headers=headers,
        )
        forbidden_list = await client.get("/support/requests", headers=headers)

    assert unauthenticated.status_code == 401
    assert invalid.status_code == 422
    assert cross_factory.status_code == 404
    assert cross_machine.status_code == 404
    assert forbidden_list.status_code == 403
    assert provider.messages == []


@pytest.mark.anyio
async def test_support_submission_is_rate_limited_without_losing_first_request(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    limited = support_settings(settings).model_copy(
        update={
            "mutation_rate_limit_enabled": True,
            "mutation_rate_limit_requests": 1,
            "mutation_rate_limit_window_seconds": 60,
        }
    )
    provider = RecordingEmailProvider()
    store = CountingRateLimitStore()
    async with ai_api_client(limited, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_support_email_provider] = lambda: provider
        application.dependency_overrides[get_auth_rate_limit_store] = lambda: store
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="rate-limited-support@example.com",
        )
        first = await client.post(
            "/support/requests", json=support_payload(), headers=headers
        )
        limited_response = await client.post(
            "/support/requests", json=support_payload(), headers=headers
        )

    assert first.status_code == 201
    assert limited_response.status_code == 429
    assert limited_response.headers["retry-after"] == "60"
    assert len(provider.messages) == 1


@pytest.mark.anyio
async def test_support_resend_stops_at_the_configured_bound(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    provider = RecordingEmailProvider(fail=True)
    async with ai_api_client(
        support_settings(settings), session_factory, tmp_path=tmp_path
    ) as (client, application):
        application.dependency_overrides[get_support_email_provider] = lambda: provider
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="bounded-support-admin@example.com",
        )
        created = await client.post(
            "/support/requests", json=support_payload(), headers=headers
        )
        request_id = created.json()["id"]
        second = await client.post(
            f"/support/requests/{request_id}/resend", headers=headers
        )
        third = await client.post(
            f"/support/requests/{request_id}/resend", headers=headers
        )
        rejected = await client.post(
            f"/support/requests/{request_id}/resend", headers=headers
        )

    assert created.json()["delivery_attempts"] == 1
    assert second.json()["delivery_attempts"] == 2
    assert third.json()["delivery_attempts"] == 3
    assert rejected.status_code == 409
    assert "retry limit" in rejected.json()["detail"].lower()
    assert len(provider.messages) == 3

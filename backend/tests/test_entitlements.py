"""Central entitlement resolution, quota, metering, and override tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from app.billing.catalog import PLAN_CATALOG, get_plan
from app.config.settings import Settings
from app.models.billing import (
    BillingAuditEvent,
    BillingPlan,
    Subscription,
    UsageCounter,
)
from app.models.manufacturing import Company, Factory
from app.models.user import User, UserRole
from app.services.entitlements import (
    EntitlementService,
    FeatureNotEntitledError,
    QuotaExceededError,
    SubscriptionAccessError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers
from tests.test_billing_provider_lifecycle import _actor


async def _activate(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    company_id,
    plan_code: str,
    status: str = "active",
) -> Subscription:
    definition = get_plan(plan_code)
    assert definition is not None
    async with session_factory() as session:
        plan = await session.scalar(
            select(BillingPlan).where(BillingPlan.code == plan_code)
        )
        if plan is None:
            plan = BillingPlan(
                id=uuid5(NAMESPACE_URL, f"entitlement-test:{plan_code}"),
                code=plan_code,
                name=definition.name,
                currency=definition.currency,
                monthly_price_minor=definition.monthly_price_minor,
                is_active=True,
            )
            session.add(plan)
            await session.flush()
        subscription = Subscription(
            company_id=company_id,
            plan_id=plan.id,
            provider="paymob",
            status=status,
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=30),
            grace_period_ends_at=(
                datetime.now(UTC) + timedelta(days=7) if status == "past_due" else None
            ),
            status_changed_at=datetime.now(UTC),
        )
        session.add(subscription)
        await session.commit()
        return subscription


@pytest.mark.anyio
@pytest.mark.parametrize("plan_code", [item.code for item in PLAN_CATALOG])
async def test_all_catalogue_plans_resolve_exact_entitlements(
    session_factory: async_sessionmaker[AsyncSession], plan_code: str
) -> None:
    actor = await _actor(session_factory)
    await _activate(session_factory, company_id=actor.company_id, plan_code=plan_code)
    async with session_factory() as session:
        snapshot = await EntitlementService(session).snapshot(actor.company_id)
    definition = get_plan(plan_code)
    assert definition is not None
    resolved = {item.key: item for item in snapshot.items}
    assert snapshot.plan_code == plan_code
    assert snapshot.access_mode == "full"
    for key, configured in definition.entitlements.items():
        response_key = "document_storage_bytes" if key == "document_storage_gb" else key
        assert response_key in resolved
        item = resolved[response_key]
        if isinstance(configured, bool):
            assert item.enabled is configured
        elif key == "document_storage_gb":
            assert item.limit == configured * 1024**3
        else:
            assert item.limit == configured


@pytest.mark.anyio
async def test_exact_resource_boundary_and_structured_quota_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    await _activate(session_factory, company_id=actor.company_id, plan_code="starter")
    async with session_factory() as session:
        company = await session.get(Company, actor.company_id)
        assert company is not None
        session.add(Factory(company_id=company.id, name="At limit"))
        await session.commit()
        service = EntitlementService(session)
        with pytest.raises(QuotaExceededError) as captured:
            await service.require_capacity(actor.company_id, "factories")
        detail = captured.value.as_detail()
        assert detail["code"] == "quota_exceeded"
        assert detail["current"] == 1
        assert detail["maximum"] == 1
        assert detail["recommended_plan"] == "professional"


@pytest.mark.anyio
async def test_rag_meter_is_atomic_idempotent_and_rejects_overage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    await _activate(session_factory, company_id=actor.company_id, plan_code="starter")
    async with session_factory() as session:
        service = EntitlementService(session)
        first = await service.consume(
            actor.company_id,
            "monthly_rag_queries",
            quantity=500,
            idempotency_key="rag-batch-1",
        )
        replay = await service.consume(
            actor.company_id,
            "monthly_rag_queries",
            quantity=500,
            idempotency_key="rag-batch-1",
        )
        assert first is not None and first.used == 500
        assert replay is not None and replay.used == 500
        with pytest.raises(QuotaExceededError) as captured:
            await service.consume(
                actor.company_id,
                "monthly_rag_queries",
                quantity=1,
                idempotency_key="rag-over-limit",
            )
        assert captured.value.period_start is not None
        assert captured.value.period_end is not None
        await session.commit()
        counter = await session.scalar(
            select(UsageCounter).where(
                UsageCounter.company_id == actor.company_id,
                UsageCounter.metric == "monthly_rag_queries",
            )
        )
        assert counter is not None and counter.quantity == 500


@pytest.mark.anyio
async def test_monthly_usage_resets_without_mutating_prior_period(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    await _activate(session_factory, company_id=actor.company_id, plan_code="starter")
    now = datetime.now(UTC)
    current_start = now.replace(day=1).date()
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end.replace(day=1)
    async with session_factory() as session:
        session.add(
            UsageCounter(
                company_id=actor.company_id,
                metric="monthly_rag_queries",
                period_start=prior_start,
                period_end=prior_end,
                quantity=500,
            )
        )
        await session.commit()
        current = await EntitlementService(session).consume(
            actor.company_id,
            "monthly_rag_queries",
            quantity=1,
            idempotency_key="new-period-query",
        )
        await session.commit()
        assert current is not None and current.used == 1
        counters = list(
            (
                await session.scalars(
                    select(UsageCounter)
                    .where(UsageCounter.company_id == actor.company_id)
                    .order_by(UsageCounter.period_start)
                )
            ).all()
        )
        assert [item.quantity for item in counters] == [500, 1]


@pytest.mark.anyio
async def test_concurrent_meter_updates_do_not_lose_increments(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    await _activate(
        session_factory, company_id=actor.company_id, plan_code="professional"
    )

    async def consume(index: int) -> None:
        async with session_factory() as session:
            await EntitlementService(session).consume(
                actor.company_id,
                "monthly_rag_queries",
                quantity=10,
                idempotency_key=f"concurrent-{index}",
            )
            await session.commit()

    await asyncio.gather(*(consume(index) for index in range(10)))
    async with session_factory() as session:
        counter = await session.scalar(
            select(UsageCounter).where(
                UsageCounter.company_id == actor.company_id,
                UsageCounter.metric == "monthly_rag_queries",
            )
        )
        assert counter is not None and counter.quantity == 100


@pytest.mark.anyio
async def test_usage_and_overrides_are_cross_tenant_isolated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    await _activate(session_factory, company_id=actor.company_id, plan_code="starter")
    company_b_id = uuid4()
    async with session_factory() as session:
        session.add(
            Company(
                id=company_b_id,
                name=f"Tenant {company_b_id}",
                normalized_name=f"tenant {company_b_id}",
            )
        )
        await session.commit()
    await _activate(session_factory, company_id=company_b_id, plan_code="starter")

    async with session_factory() as session:
        service = EntitlementService(session)
        await service.consume(
            actor.company_id,
            "monthly_rag_queries",
            quantity=3,
            idempotency_key="tenant-a",
        )
        await service.consume(
            company_b_id,
            "monthly_rag_queries",
            quantity=7,
            idempotency_key="tenant-b",
        )
        await service.set_override(
            company_id=actor.company_id,
            actor_user_id=actor.id,
            key="factories",
            integer_limit=3,
            enabled=None,
            reason="Tenant A only",
            expires_at=None,
        )
        first = await service.snapshot(actor.company_id)
        second = await service.snapshot(company_b_id)
        first_values = {item.key: item for item in first.items}
        second_values = {item.key: item for item in second.items}
        assert first_values["monthly_rag_queries"].used == 3
        assert second_values["monthly_rag_queries"].used == 7
        assert first_values["factories"].limit == 3
        assert first_values["factories"].source == "override"
        assert second_values["factories"].limit == 1
        assert second_values["factories"].source == "plan"


@pytest.mark.anyio
async def test_subscription_states_control_mutations_and_preserve_visibility(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    subscription = await _activate(
        session_factory,
        company_id=actor.company_id,
        plan_code="professional",
        status="past_due",
    )
    async with session_factory() as session:
        service = EntitlementService(session)
        await service.require_feature(actor.company_id, "model_training")
        entity = await session.get(Subscription, subscription.id)
        assert entity is not None
        entity.status = "suspended"
        await session.commit()
        visible = await service.snapshot(actor.company_id)
        assert visible.access_mode == "read_only"
        with pytest.raises(SubscriptionAccessError):
            await service.require_capacity(actor.company_id, "factories")


@pytest.mark.anyio
async def test_starter_training_denial_and_audited_manual_override(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    await _activate(session_factory, company_id=actor.company_id, plan_code="starter")
    async with session_factory() as session:
        service = EntitlementService(session)
        with pytest.raises(FeatureNotEntitledError) as captured:
            await service.require_feature(actor.company_id, "model_training")
        assert captured.value.recommended_plan == "professional"
        await service.set_override(
            company_id=actor.company_id,
            actor_user_id=actor.id,
            key="model_training",
            integer_limit=None,
            enabled=True,
            reason="Temporary governed pilot",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        await service.require_feature(actor.company_id, "model_training")
        audit = await session.scalar(
            select(BillingAuditEvent).where(
                BillingAuditEvent.company_id == actor.company_id,
                BillingAuditEvent.action == "entitlement.override_set",
            )
        )
        assert audit is not None
        assert audit.safe_metadata["reason"] == "Temporary governed pilot"


@pytest.mark.anyio
async def test_downgrade_overage_is_read_only_and_never_deletes_resources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor = await _actor(session_factory)
    subscription = await _activate(
        session_factory, company_id=actor.company_id, plan_code="professional"
    )
    async with session_factory() as session:
        session.add_all(
            [
                Factory(company_id=actor.company_id, name="Factory A"),
                Factory(company_id=actor.company_id, name="Factory B"),
            ]
        )
        starter = BillingPlan(
            id=uuid4(),
            code="starter",
            name="Starter",
            currency="EGP",
            monthly_price_minor=100_000,
            is_active=True,
        )
        session.add(starter)
        entity = await session.get(Subscription, subscription.id)
        assert entity is not None
        entity.plan_id = starter.id
        await session.commit()
        snapshot = await EntitlementService(session).snapshot(actor.company_id)
        factories = next(item for item in snapshot.items if item.key == "factories")
        assert factories.used == 2
        assert factories.over_limit is True
        with pytest.raises(QuotaExceededError):
            await EntitlementService(session).require_capacity(
                actor.company_id, "factories"
            )
        assert (
            await session.scalar(select(Factory).where(Factory.name == "Factory A"))
            is not None
        )


@pytest.mark.anyio
async def test_entitlement_api_enforces_quota_and_audited_override(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    enforced = settings.model_copy(update={"billing_entitlements_enforced": True})
    async with ai_api_client(enforced, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="entitlement-api-admin@example.com",
        )
        async with session_factory() as session:
            actor = await session.scalar(
                select(User).where(User.email == "entitlement-api-admin@example.com")
            )
            assert actor is not None
            company_id = actor.company_id
        await _activate(session_factory, company_id=company_id, plan_code="starter")

        snapshot = await client.get("/billing/entitlements", headers=headers)
        first = await client.post(
            "/factories",
            headers=headers,
            json={"company_id": str(company_id), "name": "Factory One"},
        )
        denied = await client.post(
            "/factories",
            headers=headers,
            json={"company_id": str(company_id), "name": "Factory Two"},
        )
        async with session_factory() as session:
            platform_actor = await session.scalar(
                select(User).where(User.email == "entitlement-api-admin@example.com")
            )
            assert platform_actor is not None
            platform_actor.is_platform_operator = True
            await session.commit()
        override = await client.put(
            f"/billing/platform/tenants/{company_id}/entitlement-overrides/factories",
            headers=headers,
            json={
                "integer_limit": 2,
                "reason": "Approved temporary expansion",
            },
        )
        second = await client.post(
            "/factories",
            headers=headers,
            json={"company_id": str(company_id), "name": "Factory Two"},
        )
        usage = await client.get("/billing/admin/usage", headers=headers)

        assert snapshot.status_code == 200
        assert snapshot.json()["plan_code"] == "starter"
        assert first.status_code == 201, first.text
        assert denied.status_code == 402
        assert denied.json()["detail"] == {
            "code": "quota_exceeded",
            "message": "The 'factories' quota has been reached.",
            "entitlement": "factories",
            "current": 1,
            "maximum": 1,
            "period_start": None,
            "period_end": None,
            "recommended_plan": "professional",
        }
        assert override.status_code == 200, override.text
        assert override.json()["integer_limit"] == 2
        assert second.status_code == 201, second.text
        factories = next(
            item for item in usage.json()["items"] if item["key"] == "factories"
        )
        assert factories["used"] == 2
        assert factories["source"] == "override"

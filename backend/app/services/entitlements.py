"""Central subscription entitlement resolution and atomic usage metering."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    Integer,
    String,
    Uuid,
    bindparam,
    delete,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.catalog import PLAN_CATALOG, PlanDefinition, get_plan
from app.models.ai_governance import TrainingJob
from app.models.billing import (
    BillingAuditEvent,
    EntitlementOverride,
    Subscription,
    UsageCounter,
    UsageLedgerEvent,
)
from app.models.datasets import Dataset, DatasetVersion, DocumentRecord
from app.models.demo_experience import ReportSchedule
from app.models.manufacturing import Factory, Machine
from app.models.user import TeamInvitation, User
from app.repositories.billing import BillingRepository


class EntitlementError(RuntimeError):
    code = "entitlement_error"

    def as_detail(self) -> dict[str, object]:
        return {"code": self.code, "message": str(self)}


class SubscriptionAccessError(EntitlementError):
    code = "subscription_access_required"

    def __init__(self, message: str, *, state: str | None) -> None:
        super().__init__(message)
        self.state = state

    def as_detail(self) -> dict[str, object]:
        return {**super().as_detail(), "subscription_state": self.state}


class FeatureNotEntitledError(EntitlementError):
    code = "feature_not_entitled"

    def __init__(self, key: str, *, recommended_plan: str | None) -> None:
        super().__init__(f"The '{key}' feature is not included in this plan.")
        self.key = key
        self.recommended_plan = recommended_plan

    def as_detail(self) -> dict[str, object]:
        return {
            **super().as_detail(),
            "entitlement": self.key,
            "recommended_plan": self.recommended_plan,
        }


class QuotaExceededError(EntitlementError):
    code = "quota_exceeded"

    def __init__(
        self,
        key: str,
        *,
        current: int,
        maximum: int,
        period_start: date | None,
        period_end: date | None,
        recommended_plan: str | None,
    ) -> None:
        super().__init__(f"The '{key}' quota has been reached.")
        self.key = key
        self.current = current
        self.maximum = maximum
        self.period_start = period_start
        self.period_end = period_end
        self.recommended_plan = recommended_plan

    def as_detail(self) -> dict[str, object]:
        return {
            **super().as_detail(),
            "entitlement": self.key,
            "current": self.current,
            "maximum": self.maximum,
            "period_start": self.period_start.isoformat()
            if self.period_start
            else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "recommended_plan": self.recommended_plan,
        }


class EntitlementOverrideError(EntitlementError):
    code = "invalid_entitlement_override"


@dataclass(frozen=True, slots=True)
class EntitlementValue:
    key: str
    enabled: bool | None
    limit: int | None
    used: int | None
    remaining: int | None
    over_limit: bool
    source: str
    period_start: date | None = None
    period_end: date | None = None


@dataclass(frozen=True, slots=True)
class EntitlementSnapshot:
    company_id: UUID
    subscription_status: str | None
    access_mode: str
    plan_code: str | None
    items: tuple[EntitlementValue, ...]
    recommended_plan: str | None


_METERED_KEYS = {"monthly_rag_queries"}
_FEATURE_KEYS = {"model_training", "advanced_reports", "audit_log"}


def _month_period(now: datetime) -> tuple[date, date]:
    start = date(now.year, now.month, 1)
    end = date(now.year, now.month, calendar.monthrange(now.year, now.month)[1])
    return start, end


class EntitlementService:
    """The only service allowed to decide plan access or increment usage."""

    def __init__(self, session: AsyncSession, *, enforced: bool = True) -> None:
        self._session = session
        self._billing = BillingRepository(session)
        self._enforced = enforced

    async def snapshot(self, company_id: UUID) -> EntitlementSnapshot:
        subscription = await self._billing.get_company_subscription(company_id)
        if subscription is None:
            return EntitlementSnapshot(
                company_id=company_id,
                subscription_status=None,
                access_mode="unmanaged" if not self._enforced else "blocked",
                plan_code=None,
                items=(),
                recommended_plan="starter",
            )
        plan = await self._plan(subscription)
        values = await self._effective_values(company_id, plan)
        items = tuple(
            [
                await self._value_snapshot(
                    company_id, key, value, source=source
                )
                for key, (value, source) in sorted(values.items())
            ]
        )
        access_mode = (
            "full"
            if subscription.status in {"active", "trialing", "past_due"}
            else "read_only"
            if subscription.status == "suspended"
            else "blocked"
        )
        return EntitlementSnapshot(
            company_id=company_id,
            subscription_status=subscription.status,
            access_mode=access_mode,
            plan_code=plan.code,
            items=items,
            recommended_plan=self._recommend_plan(plan, values),
        )

    async def require_feature(self, company_id: UUID, key: str) -> None:
        if not self._enforced:
            return
        subscription, plan, values = await self._access_context(company_id, lock=True)
        _ = subscription
        value = values.get(key)
        if not isinstance(value, tuple) or value[0] is not True:
            raise FeatureNotEntitledError(
                key, recommended_plan=self._recommend_for_key(plan, key, boolean=True)
            )

    async def require_capacity(
        self, company_id: UUID, key: str, *, increment: int = 1
    ) -> EntitlementValue | None:
        if not self._enforced:
            return None
        if increment < 0:
            raise ValueError("increment cannot be negative")
        _subscription, plan, values = await self._access_context(
            company_id, lock=True
        )
        configured = values.get(key)
        if configured is None or isinstance(configured[0], bool):
            raise FeatureNotEntitledError(
                key, recommended_plan=self._recommend_for_key(plan, key)
            )
        maximum = int(configured[0])
        current = await self._current_usage(company_id, key)
        if current + increment > maximum:
            raise QuotaExceededError(
                key,
                current=current,
                maximum=maximum,
                period_start=None,
                period_end=None,
                recommended_plan=self._recommend_for_key(
                    plan, key, minimum=current + increment
                ),
            )
        return EntitlementValue(
            key=key,
            enabled=None,
            limit=maximum,
            used=current,
            remaining=max(0, maximum - current),
            over_limit=current > maximum,
            source=configured[1],
        )

    async def consume(
        self,
        company_id: UUID,
        key: str,
        *,
        quantity: int,
        idempotency_key: str,
    ) -> EntitlementValue | None:
        if not self._enforced:
            return None
        if key not in _METERED_KEYS or quantity <= 0:
            raise ValueError("Unsupported metered entitlement increment.")
        _subscription, plan, values = await self._access_context(
            company_id, lock=True
        )
        configured = values.get(key)
        if configured is None or isinstance(configured[0], bool):
            raise FeatureNotEntitledError(
                key, recommended_plan=self._recommend_for_key(plan, key)
            )
        maximum = int(configured[0])
        period_start, period_end = _month_period(datetime.now(UTC))
        ledger_id = uuid4()
        ledger_insert = text(
            "INSERT INTO usage_ledger_events "
            "(id, company_id, metric, idempotency_key, quantity, period_start) "
            "VALUES (:id, :company_id, :metric, :key, :quantity, :period_start) "
            "ON CONFLICT (company_id, metric, idempotency_key) DO NOTHING "
            "RETURNING id"
        ).bindparams(
            bindparam("id", value=ledger_id, type_=Uuid(as_uuid=True)),
            bindparam("company_id", value=company_id, type_=Uuid(as_uuid=True)),
            bindparam("metric", value=key, type_=String(64)),
            bindparam("key", value=idempotency_key, type_=String(128)),
            bindparam("quantity", value=quantity, type_=Integer()),
            bindparam("period_start", value=period_start, type_=Date()),
        )
        claimed = (await self._session.execute(ledger_insert)).scalar_one_or_none()
        if claimed is None:
            return await self._value_snapshot(
                company_id, key, configured[0], source=configured[1]
            )

        counter_id = uuid4()
        statement = text(
            "INSERT INTO usage_counters "
            "(id, company_id, metric, period_start, period_end, quantity) "
            "VALUES (:id, :company_id, :metric, :period_start, :period_end, :quantity) "
            "ON CONFLICT (company_id, metric, period_start) DO UPDATE SET "
            "quantity = usage_counters.quantity + :quantity, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE usage_counters.quantity + :quantity <= :maximum "
            "RETURNING quantity"
        ).bindparams(
            bindparam(
                "id", value=counter_id, type_=Uuid(as_uuid=True)
            ),
            bindparam(
                "company_id", value=company_id, type_=Uuid(as_uuid=True)
            ),
            bindparam(
                "metric", value=key, type_=String(64)
            ),
            bindparam(
                "period_start", value=period_start, type_=Date()
            ),
            bindparam(
                "period_end", value=period_end, type_=Date()
            ),
            bindparam(
                "quantity", value=quantity, type_=Integer()
            ),
            bindparam(
                "maximum", value=maximum, type_=Integer()
            ),
        )
        updated = (await self._session.execute(statement)).scalar_one_or_none()
        if updated is None:
            await self._session.execute(
                delete(UsageLedgerEvent).where(UsageLedgerEvent.id == ledger_id)
            )
            current = await self._metered_usage(company_id, key, period_start)
            raise QuotaExceededError(
                key,
                current=current,
                maximum=maximum,
                period_start=period_start,
                period_end=period_end,
                recommended_plan=self._recommend_for_key(
                    plan, key, minimum=current + quantity
                ),
            )
        return EntitlementValue(
            key=key,
            enabled=None,
            limit=maximum,
            used=int(updated),
            remaining=max(0, maximum - int(updated)),
            over_limit=int(updated) > maximum,
            source=configured[1],
            period_start=period_start,
            period_end=period_end,
        )

    async def require_storage_bytes(
        self, company_id: UUID, *, incoming_bytes: int
    ) -> EntitlementValue | None:
        if not self._enforced:
            return None
        if incoming_bytes < 0:
            raise ValueError("incoming_bytes cannot be negative")
        _subscription, plan, values = await self._access_context(
            company_id, lock=True
        )
        configured = values.get("document_storage_gb")
        if configured is None or isinstance(configured[0], bool):
            raise FeatureNotEntitledError(
                "document_storage_bytes",
                recommended_plan=self._recommend_for_key(
                    plan, "document_storage_gb"
                ),
            )
        maximum = int(configured[0]) * 1024**3
        current = await self._storage_bytes(company_id)
        if current + incoming_bytes > maximum:
            raise QuotaExceededError(
                "document_storage_bytes",
                current=current,
                maximum=maximum,
                period_start=None,
                period_end=None,
                recommended_plan=self._recommend_for_key(
                    plan,
                    "document_storage_gb",
                    minimum=(current + incoming_bytes + 1024**3 - 1) // 1024**3,
                ),
            )
        return EntitlementValue(
            key="document_storage_bytes",
            enabled=None,
            limit=maximum,
            used=current,
            remaining=max(0, maximum - current),
            over_limit=current > maximum,
            source=configured[1],
        )

    async def set_override(
        self,
        *,
        company_id: UUID,
        actor_user_id: UUID,
        key: str,
        integer_limit: int | None,
        enabled: bool | None,
        reason: str,
        expires_at: datetime | None,
    ) -> EntitlementOverride:
        known = {item for plan in PLAN_CATALOG for item in plan.entitlements}
        if key not in known or (integer_limit is None) == (enabled is None):
            raise EntitlementOverrideError("The override key or value is invalid.")
        existing = await self._session.scalar(
            select(EntitlementOverride)
            .where(
                EntitlementOverride.company_id == company_id,
                EntitlementOverride.key == key,
            )
            .with_for_update()
        )
        if existing is None:
            existing = EntitlementOverride(
                company_id=company_id,
                key=key,
                integer_limit=integer_limit,
                enabled=enabled,
                reason=reason,
                created_by_user_id=actor_user_id,
                expires_at=expires_at,
            )
            self._session.add(existing)
        else:
            existing.integer_limit = integer_limit
            existing.enabled = enabled
            existing.reason = reason
            existing.created_by_user_id = actor_user_id
            existing.expires_at = expires_at
        self._session.add(
            BillingAuditEvent(
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="entitlement.override_set",
                result="succeeded",
                safe_metadata={
                    "key": key,
                    "integer_limit": integer_limit,
                    "enabled": enabled,
                    "reason": reason,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
            )
        )
        await self._session.commit()
        await self._session.refresh(existing)
        return existing

    async def delete_override(
        self, *, company_id: UUID, actor_user_id: UUID, key: str
    ) -> bool:
        existing = await self._session.scalar(
            select(EntitlementOverride).where(
                EntitlementOverride.company_id == company_id,
                EntitlementOverride.key == key,
            )
        )
        if existing is None:
            return False
        await self._session.delete(existing)
        self._session.add(
            BillingAuditEvent(
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="entitlement.override_deleted",
                result="succeeded",
                safe_metadata={"key": key},
            )
        )
        await self._session.commit()
        return True

    async def _access_context(
        self, company_id: UUID, *, lock: bool
    ) -> tuple[
        Subscription, PlanDefinition, dict[str, tuple[int | bool, str]]
    ]:
        subscription = await self._billing.get_company_subscription(
            company_id, lock=lock
        )
        if subscription is None:
            raise SubscriptionAccessError(
                "A paid subscription is required for this action.", state=None
            )
        if subscription.status not in {"active", "trialing", "past_due"}:
            raise SubscriptionAccessError(
                "The subscription is read-only or inactive.",
                state=subscription.status,
            )
        plan = await self._plan(subscription)
        return subscription, plan, await self._effective_values(company_id, plan)

    async def _plan(self, subscription: Subscription) -> PlanDefinition:
        record = await self._billing.get_plan_by_id(subscription.plan_id)
        plan = get_plan(record.code) if record is not None else None
        if plan is None:
            raise SubscriptionAccessError(
                "The subscription plan is unavailable.", state=subscription.status
            )
        return plan

    async def _effective_values(
        self, company_id: UUID, plan: PlanDefinition
    ) -> dict[str, tuple[int | bool, str]]:
        values = {key: (value, "plan") for key, value in plan.entitlements.items()}
        now = datetime.now(UTC)
        overrides = (
            await self._session.scalars(
                select(EntitlementOverride).where(
                    EntitlementOverride.company_id == company_id,
                    or_(
                        EntitlementOverride.expires_at.is_(None),
                        EntitlementOverride.expires_at > now,
                    ),
                )
            )
        ).all()
        for override in overrides:
            value: int | bool | None = (
                override.integer_limit
                if override.integer_limit is not None
                else override.enabled
            )
            if value is not None:
                values[override.key] = (value, "override")
        return values

    async def _value_snapshot(
        self,
        company_id: UUID,
        key: str,
        configured: int | bool,
        *,
        source: str,
    ) -> EntitlementValue:
        if isinstance(configured, bool):
            return EntitlementValue(
                key=key,
                enabled=configured,
                limit=None,
                used=None,
                remaining=None,
                over_limit=False,
                source=source,
            )
        period_start = period_end = None
        response_key = key
        if key in _METERED_KEYS:
            period_start, period_end = _month_period(datetime.now(UTC))
            used = await self._metered_usage(company_id, key, period_start)
        elif key == "document_storage_gb":
            response_key = "document_storage_bytes"
            configured *= 1024**3
            used = await self._storage_bytes(company_id)
        else:
            used = await self._current_usage(company_id, key)
        return EntitlementValue(
            key=response_key,
            enabled=None,
            limit=configured,
            used=used,
            remaining=max(0, configured - used),
            over_limit=used > configured,
            source=source,
            period_start=period_start,
            period_end=period_end,
        )

    async def _current_usage(self, company_id: UUID, key: str) -> int:
        now = datetime.now(UTC)
        if key == "team_members":
            users = int(
                await self._session.scalar(
                    select(func.count()).select_from(User).where(
                        User.company_id == company_id, User.is_active
                    )
                )
                or 0
            )
            pending = int(
                await self._session.scalar(
                    select(func.count()).select_from(TeamInvitation).where(
                        TeamInvitation.company_id == company_id,
                        TeamInvitation.accepted_at.is_(None),
                        TeamInvitation.revoked_at.is_(None),
                        TeamInvitation.expires_at > now,
                    )
                )
                or 0
            )
            return users + pending
        if key == "factories":
            return int(
                await self._session.scalar(
                    select(func.count()).select_from(Factory).where(
                        Factory.company_id == company_id,
                        Factory.deleted_at.is_(None),
                    )
                )
                or 0
            )
        if key == "machines":
            return int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(Machine)
                    .join(Factory, Factory.id == Machine.factory_id)
                    .where(
                        Factory.company_id == company_id,
                        Factory.deleted_at.is_(None),
                        Machine.deleted_at.is_(None),
                    )
                )
                or 0
            )
        if key == "documents":
            return int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(DocumentRecord)
                    .join(
                        DatasetVersion,
                        DatasetVersion.id == DocumentRecord.dataset_version_id,
                    )
                    .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                    .where(Dataset.company_id == company_id)
                )
                or 0
            )
        if key == "document_storage_gb":
            return await self._storage_bytes(company_id)
        if key == "training_concurrency":
            return int(
                await self._session.scalar(
                    select(func.count()).select_from(TrainingJob).where(
                        TrainingJob.company_id == company_id,
                        TrainingJob.status.in_(("queued", "running")),
                    )
                )
                or 0
            )
        if key == "scheduled_reports":
            return int(
                await self._session.scalar(
                    select(func.count()).select_from(ReportSchedule).where(
                        ReportSchedule.company_id == company_id
                    )
                )
                or 0
            )
        return 0

    async def _storage_bytes(self, company_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.coalesce(func.sum(DatasetVersion.size_bytes), 0))
                .select_from(DatasetVersion)
                .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                .where(Dataset.company_id == company_id)
            )
            or 0
        )

    async def _metered_usage(
        self, company_id: UUID, key: str, period_start: date
    ) -> int:
        return int(
            await self._session.scalar(
                select(UsageCounter.quantity).where(
                    UsageCounter.company_id == company_id,
                    UsageCounter.metric == key,
                    UsageCounter.period_start == period_start,
                )
            )
            or 0
        )

    @staticmethod
    def _recommend_plan(
        current: PlanDefinition, values: dict[str, tuple[int | bool, str]]
    ) -> str | None:
        _ = values
        return next(
            (
                plan.code
                for plan in PLAN_CATALOG
                if plan.monthly_price_minor > current.monthly_price_minor
            ),
            None,
        )

    @staticmethod
    def _recommend_for_key(
        current: PlanDefinition,
        key: str,
        *,
        minimum: int | None = None,
        boolean: bool = False,
    ) -> str | None:
        for plan in PLAN_CATALOG:
            if plan.monthly_price_minor <= current.monthly_price_minor:
                continue
            value = plan.entitlements.get(key)
            if boolean and value is True:
                return plan.code
            if (
                not boolean
                and isinstance(value, int)
                and not isinstance(value, bool)
                and (minimum is None or value >= minimum)
            ):
                return plan.code
        return None

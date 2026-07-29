"""Public and authenticated billing API schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PlanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    monthly_price_minor: int
    currency: str
    description: str
    entitlements: dict[str, int | bool]


class PlanListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[PlanResponse]


class BillingDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone_number: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
    city: str = Field(min_length=1, max_length=100)
    country: str = Field(default="EG", pattern=r"^[A-Z]{2}$")
    street: str = Field(min_length=1, max_length=160)


class CheckoutCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$")
    billing_details: BillingDetailsRequest


class CheckoutResponse(BaseModel):
    payment_id: UUID
    subscription_id: UUID
    provider: str
    provider_checkout_id: str
    checkout_url: str
    plan_code: str
    amount_minor: int
    currency: str
    status: str
    reused: bool
    purpose: str
    failure_url: str


class PaymentStatusResponse(BaseModel):
    payment_id: UUID
    plan_code: str | None
    amount_minor: int
    currency: str
    status: str
    failure_code: str | None
    purpose: str
    provider: str
    provider_payment_id: str | None
    provider_checkout_id: str | None
    provider_occurred_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SubscriptionResponse(BaseModel):
    subscription_id: UUID
    status: str
    plan_code: str
    pending_plan_code: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    grace_period_ends_at: datetime | None
    cancel_at_period_end: bool
    suspended_at: datetime | None
    ended_at: datetime | None
    version: int
    allowed_actions: list[str]


class SubscriptionEnvelope(BaseModel):
    item: SubscriptionResponse | None


class SubscriptionCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["period_end", "immediate"] = "period_end"


class PaymentHistoryResponse(BaseModel):
    items: list[PaymentStatusResponse]
    total: int
    page: int
    page_size: int


class InvoiceReferenceResponse(BaseModel):
    invoice_id: UUID
    payment_id: UUID | None
    provider: str
    provider_invoice_id: str
    receipt_url: str | None
    amount_minor: int
    currency: str
    status: str
    issued_at: datetime | None


class InvoiceHistoryResponse(BaseModel):
    items: list[InvoiceReferenceResponse]
    total: int
    page: int
    page_size: int


class BillingAuditEventResponse(BaseModel):
    event_id: UUID
    actor_user_id: UUID | None
    action: str
    result: str
    safe_metadata: dict[str, object]
    created_at: datetime


class BillingAuditHistoryResponse(BaseModel):
    items: list[BillingAuditEventResponse]
    total: int
    page: int
    page_size: int


class BillingProviderEventResponse(BaseModel):
    event_id: UUID
    provider: str
    provider_event_id: str
    event_type: str
    status: str
    attempts: int
    last_error: str | None
    received_at: datetime
    processed_at: datetime | None


class BillingProviderEventHistoryResponse(BaseModel):
    items: list[BillingProviderEventResponse]
    total: int
    page: int
    page_size: int


class EntitlementItemResponse(BaseModel):
    key: str
    enabled: bool | None
    limit: int | None
    used: int | None
    remaining: int | None
    over_limit: bool
    source: str
    period_start: str | None
    period_end: str | None


class EntitlementSnapshotResponse(BaseModel):
    subscription_status: str | None
    access_mode: str
    plan_code: str | None
    items: list[EntitlementItemResponse]
    recommended_plan: str | None


class UpgradeRecommendationResponse(BaseModel):
    current_plan: str | None
    recommended_plan: str | None
    over_limit_entitlements: list[str]


class EntitlementOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integer_limit: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    reason: str = Field(min_length=3, max_length=500)
    expires_at: datetime | None = None


class EntitlementOverrideResponse(BaseModel):
    override_id: UUID
    key: str
    integer_limit: int | None
    enabled: bool | None
    reason: str
    expires_at: datetime | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class WebhookAcceptedResponse(BaseModel):
    accepted: bool = True
    duplicate: bool

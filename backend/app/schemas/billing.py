"""Public and authenticated billing API schemas."""

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
    provider: str
    provider_checkout_id: str
    checkout_url: str
    plan_code: str
    amount_minor: int
    currency: str
    status: str
    reused: bool
    failure_url: str


class PaymentStatusResponse(BaseModel):
    payment_id: UUID
    plan_code: str | None
    amount_minor: int
    currency: str
    status: str
    failure_code: str | None


class WebhookAcceptedResponse(BaseModel):
    accepted: bool = True
    duplicate: bool

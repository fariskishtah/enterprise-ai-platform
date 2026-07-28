"""Public and authenticated billing API schemas."""

from pydantic import BaseModel, ConfigDict


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

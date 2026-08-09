"""Billing catalogue contract tests."""

from dataclasses import replace

import app.billing.catalog as billing_catalog
import pytest
from app.billing.catalog import PLAN_CATALOG, active_plans, get_plan
from app.schemas.billing import CheckoutCreateRequest
from httpx import AsyncClient
from pydantic import ValidationError


def test_catalogue_has_backend_authoritative_egp_prices_and_quotas() -> None:
    assert [
        (plan.code, plan.monthly_price_minor, plan.currency) for plan in PLAN_CATALOG
    ] == [
        ("starter", 100_000, "EGP"),
        ("professional", 500_000, "EGP"),
        ("enterprise", 1_000_000, "EGP"),
    ]
    assert PLAN_CATALOG[0].entitlements["machines"] == 25
    assert PLAN_CATALOG[1].entitlements["model_training"] is True
    assert PLAN_CATALOG[2].entitlements["audit_log"] is True


def test_plan_lookup_normalizes_code_and_rejects_unknown_plan() -> None:
    assert get_plan(" Professional ") is PLAN_CATALOG[1]
    assert get_plan("untrusted-frontend-plan") is None


def test_disabled_plan_is_excluded_from_lookup_and_active_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled = replace(PLAN_CATALOG[0], enabled=False)
    monkeypatch.setattr(billing_catalog, "PLAN_CATALOG", (disabled, *PLAN_CATALOG[1:]))

    assert get_plan("starter") is None
    assert [plan.code for plan in active_plans()] == ["professional", "enterprise"]


@pytest.mark.parametrize("amount_minor", [100_000, 500_000, 73_421])
def test_checkout_request_rejects_every_client_supplied_amount(
    amount_minor: int,
) -> None:
    with pytest.raises(ValidationError):
        CheckoutCreateRequest.model_validate(
            {
                "plan_code": "starter",
                "amount_minor": amount_minor,
                "currency": "EGP",
                "billing_details": {
                    "first_name": "Factory",
                    "last_name": "Owner",
                    "phone_number": "+201001234567",
                    "city": "Cairo",
                    "country": "EG",
                    "street": "Industrial Zone",
                },
            }
        )


@pytest.mark.anyio
async def test_public_plan_api_returns_exact_catalogue(api_client: AsyncClient) -> None:
    response = await api_client.get("/billing/plans")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 3
    assert {item["currency"] for item in payload["items"]} == {"EGP"}
    assert [item["monthly_price_minor"] for item in payload["items"]] == [
        100_000,
        500_000,
        1_000_000,
    ]

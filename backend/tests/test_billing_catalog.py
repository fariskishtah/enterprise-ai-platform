"""Billing catalogue contract tests."""

import pytest
from app.billing.catalog import PLAN_CATALOG, get_plan
from httpx import AsyncClient


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

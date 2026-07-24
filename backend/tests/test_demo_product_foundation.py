"""Focused product-mode and feature-control foundation coverage."""

from pathlib import Path

import pytest
from app.config.settings import Settings
from app.models.user import UserRole
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers


@pytest.mark.anyio
async def test_product_features_require_authentication_and_report_safe_flags(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    enabled = settings.model_copy(
        update={
            "simplified_experience_enabled": True,
            "operations_workflow_enabled": True,
            "demo_tools_enabled": True,
        }
    )
    async with ai_api_client(enabled, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        unauthenticated = await client.get("/product/features")
        assert unauthenticated.status_code == 401

        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="product-mode-operator@example.com",
        )
        response = await client.get("/product/features", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "simplified_experience_enabled": True,
        "operations_workflow_enabled": True,
        "demo_tools_enabled": True,
    }


def test_production_rejects_demo_tools(settings: Settings) -> None:
    values = settings.model_dump()
    values.update(
        {
            "environment": "production",
            "enable_api_docs": False,
            "cors_allowed_origins": ("https://manufacturing.example.com",),
            "demo_tools_enabled": True,
        }
    )
    with pytest.raises(
        ValidationError, match="demo_tools_enabled must be false in production"
    ):
        Settings.model_validate(values)

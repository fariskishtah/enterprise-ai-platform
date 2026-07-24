"""Focused product-mode and feature-control foundation coverage."""

import os
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from app.config.settings import Settings
from app.models.user import UserRole
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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


def test_app_env_alias_enforces_production_safeguards(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("REDIS_URL", settings.redis_url)
    monkeypatch.setenv("SECRET_KEY", settings.secret_key.get_secret_value())
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["https://manufacturing.example.com"]')
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "true")
    with pytest.raises(
        ValidationError, match="demo_tools_enabled must be false in production"
    ):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("environment", "password", "expected_message"),
    [
        ("production", "disposable-only", "demo seeding is disabled in production"),
        ("staging", "", "DEMO_PASSWORD is required for local demo seeding"),
    ],
)
def test_demo_seed_fails_closed_before_network_access(
    environment: str, password: str, expected_message: str
) -> None:
    seed_environment = {
        **os.environ,
        "APP_ENV": environment,
        "DEMO_PASSWORD": password,
        "PYTHONPATH": str(REPOSITORY_ROOT / "backend"),
    }
    result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scripts" / "seed_demo.py")],
        capture_output=True,
        check=False,
        env=seed_environment,
        text=True,
        timeout=15,
    )

    assert result.returncode == 1
    assert expected_message in result.stderr
    assert "http" not in result.stderr.lower()


def test_demo_dataset_names_are_scoped_to_the_creating_user_on_collision() -> None:
    module_path = REPOSITORY_ROOT / "scripts" / "seed_demo.py"
    spec = spec_from_file_location("seed_demo_test_module", module_path)
    assert spec is not None and spec.loader is not None
    seed_demo = module_from_spec(spec)
    spec.loader.exec_module(seed_demo)

    owner_id = "current-owner"
    base_name = "DEMO Maintenance Procedures"
    company_dataset = {
        "name": base_name,
        "owner_user_id": "another-company-user",
    }
    fallback_name = f"{base_name} {seed_demo.DEMO_OWNER_FINGERPRINT}"
    owned_fallback = {
        "name": fallback_name,
        "owner_user_id": owner_id,
    }

    dataset, resolved_name = seed_demo.resolve_owned_dataset(
        [company_dataset, owned_fallback],
        name=base_name,
        owner_user_id=owner_id,
    )

    assert dataset is owned_fallback
    assert resolved_name == fallback_name

"""Focused security and lifecycle coverage for Sprints 3–5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import Settings, get_settings
from app.models.manufacturing import Company, Factory, Machine
from app.models.sensor import Sensor
from app.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.services.reporting import pdf_report, spreadsheet_safe, xlsx_report
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from app.utils.security import utc_now
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import VALID_PASSWORD, ai_api_client, auth_headers


async def _hierarchy(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> tuple[Factory, Machine, Sensor]:
    async with session_factory() as session:
        user = await session.scalar(
            select(User)
            .where(User.email == email)
            .execution_options(skip_tenant_scope=True)
        )
        assert user is not None
        factory = Factory(
            company_id=user.company_id,
            name=f"Factory {email}",
            location="Cairo",
        )
        session.add(factory)
        await session.flush()
        machine = Machine(factory_id=factory.id, name="CNC-01")
        session.add(machine)
        await session.flush()
        sensor = Sensor(
            machine_id=machine.id,
            name="temperature",
            normalized_name="temperature",
            sensor_type="temperature",
            unit="celsius",
            sampling_rate=1,
            min_value=0,
            max_value=200,
        )
        session.add(sensor)
        await session.commit()
        return factory, machine, sensor


async def _other_company_headers(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
    role: UserRole,
) -> dict[str, str]:
    async with session_factory() as session:
        company = Company(
            name=f"Other tenant {email}",
            normalized_name=f"other-tenant-{email}",
        )
        session.add(company)
        await session.flush()
        await UserService(
            repository=UserRepository(session),
            password_hasher=PasswordHasher(),
        ).create_user(
            email=email,
            password=VALID_PASSWORD,
            role=role,
            company_id=company.id,
        )
    response = await client.post(
        "/auth/login", json={"email": email, "password": VALID_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.anyio
async def test_guided_csv_preview_mapping_quality_import_and_isolation(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="guided-engineer@example.com",
        )
        operator = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="guided-operator@example.com",
        )
        await _hierarchy(session_factory, "guided-engineer@example.com")
        csv_body = (
            "timestamp,machine,sensor,value\n"
            "2026-07-24T10:00:00Z,CNC-01,temperature,72.5\n"
            "2026-07-24T10:01:00Z,CNC-01,temperature,73.0\n"
        )
        uploaded = await client.post(
            "/data-onboarding/imports",
            headers={**headers, "Idempotency-Key": "guided-import-001"},
            files={"file": ("safe.csv", csv_body, "text/csv")},
        )
        assert uploaded.status_code == 201, uploaded.text
        import_id = uploaded.json()["id"]
        assert uploaded.json()["imported_rows"] == 0
        assert len(uploaded.json()["preview"]) == 2

        repeated = await client.post(
            "/data-onboarding/imports",
            headers={**headers, "Idempotency-Key": "guided-import-001"},
            files={"file": ("safe.csv", csv_body, "text/csv")},
        )
        assert repeated.status_code == 201
        assert repeated.json()["id"] == import_id

        mapped = await client.put(
            f"/data-onboarding/imports/{import_id}/mapping",
            headers=headers,
            json={
                "mapping": {
                    "shape": "long",
                    "timestamp": "timestamp",
                    "machine": "machine",
                    "sensor": "sensor",
                    "value": "value",
                },
                "delimiter": ",",
                "has_header": True,
            },
        )
        assert mapped.status_code == 200, mapped.text
        validated = await client.post(
            f"/data-onboarding/imports/{import_id}/validate", headers=headers
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()["quality_report"]["blocking_issue_count"] == 0
        imported = await client.post(
            f"/data-onboarding/imports/{import_id}/confirm",
            headers=headers,
            json={"accept_warnings": True},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["status"] == "completed"
        assert imported.json()["imported_rows"] == 2
        assert (
            await client.get("/data-onboarding/imports", headers=operator)
        ).status_code == 403

        unsafe = await client.post(
            "/data-onboarding/imports",
            headers={**headers, "Idempotency-Key": "guided-import-unsafe"},
            files={
                "file": (
                    "unsafe.csv",
                    csv_body.replace("72.5", "=2+2"),
                    "text/csv",
                )
            },
        )
        assert unsafe.status_code == 201
        unsafe_id = unsafe.json()["id"]
        await client.put(
            f"/data-onboarding/imports/{unsafe_id}/mapping",
            headers=headers,
            json={
                "mapping": {
                    "shape": "long",
                    "timestamp": "timestamp",
                    "machine": "machine",
                    "sensor": "sensor",
                    "value": "value",
                }
            },
        )
        bad_quality = await client.post(
            f"/data-onboarding/imports/{unsafe_id}/validate", headers=headers
        )
        assert bad_quality.json()["quality_report"]["blocking_issue_count"] == 1
        blocked = await client.post(
            f"/data-onboarding/imports/{unsafe_id}/confirm",
            headers=headers,
            json={"accept_warnings": True},
        )
        assert blocked.status_code == 409


@pytest.mark.anyio
async def test_demo_scenario_layout_tv_and_tagged_reset(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    enabled = settings.model_copy(update={"demo_tools_enabled": True})
    async with ai_api_client(enabled, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        admin = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="demo-control-admin@example.com",
        )
        operator = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="demo-control-operator@example.com",
        )
        factory, machine, _sensor = await _hierarchy(
            session_factory, "demo-control-admin@example.com"
        )
        started = await client.post(
            "/demo/runs",
            headers=admin,
            json={
                "factory_id": str(factory.id),
                "machine_id": str(machine.id),
                "scenario": "warning_threshold",
                "speed": 2,
                "idempotency_key": "demo-warning-001",
            },
        )
        assert started.status_code == 201, started.text
        run_id = started.json()["id"]
        duplicate = await client.post(
            "/demo/runs",
            headers=admin,
            json={
                "factory_id": str(factory.id),
                "machine_id": str(machine.id),
                "scenario": "warning_threshold",
                "speed": 2,
                "idempotency_key": "demo-warning-001",
            },
        )
        assert duplicate.json()["id"] == run_id
        for _ in range(2):
            advanced = await client.post(f"/demo/runs/{run_id}/advance", headers=admin)
            assert advanced.status_code == 200, advanced.text
        assert advanced.json()["state_snapshot"]["risk_state"] == "warning"

        layout = await client.put(
            f"/demo/factories/{factory.id}/layout",
            headers=admin,
            json={"nodes": [{"machine_id": str(machine.id), "x": 30, "y": 40}]},
        )
        assert layout.status_code == 200, layout.text
        assert (
            await client.get(f"/demo/factories/{factory.id}/tv", headers=admin)
        ).json()["read_only"]
        assert (
            await client.put(
                f"/demo/factories/{factory.id}/layout",
                headers=operator,
                json={"nodes": []},
            )
        ).status_code == 403
        reset = await client.delete(f"/demo/runs/{run_id}/reset", headers=admin)
        assert reset.status_code == 200, reset.text
        assert reset.json()["deleted_records"] > 0


@pytest.mark.anyio
async def test_grounded_reports_expiration_schedule_failure_and_artifacts(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        admin = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="report-admin@example.com",
        )
        factory, _machine, _sensor = await _hierarchy(
            session_factory, "report-admin@example.com"
        )
        now = utc_now()
        for format_name, signature in (
            ("pdf", b"%PDF-"),
            ("xlsx", b"PK"),
            ("csv", b"metric,value"),
        ):
            created = await client.post(
                "/reporting/reports",
                headers=admin,
                json={
                    "report_type": "executive_factory_summary",
                    "format": format_name,
                    "factory_id": str(factory.id),
                    "period_start": (now - timedelta(days=7)).isoformat(),
                    "period_end": now.isoformat(),
                    "idempotency_key": f"report-{format_name}-001",
                },
            )
            assert created.status_code == 201, created.text
            downloaded = await client.get(
                f"/reporting/reports/{created.json()['id']}/download",
                headers=admin,
            )
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.content.startswith(signature)
            if format_name == "xlsx":
                with ZipFile(BytesIO(downloaded.content)) as workbook:
                    assert "xl/worksheets/sheet1.xml" in workbook.namelist()

        schedule = await client.post(
            "/reporting/schedules",
            headers=admin,
            json={
                "report_type": "executive_factory_summary",
                "format": "pdf",
                "factory_id": str(factory.id),
                "period": "last_7_days",
                "cadence": "weekly",
                "timezone": "UTC",
                "recipients": ["reviewer@example.com"],
                "enabled": False,
                "idempotency_key": "schedule-disabled-001",
            },
        )
        assert schedule.status_code == 201
        assert schedule.json()["last_result"] == "delivery_unavailable"
        enabled = await client.post(
            "/reporting/schedules",
            headers=admin,
            json={
                "report_type": "executive_factory_summary",
                "format": "pdf",
                "period": "last_7_days",
                "cadence": "weekly",
                "recipients": ["reviewer@example.com"],
                "enabled": True,
                "idempotency_key": "schedule-enabled-001",
            },
        )
        assert enabled.status_code == 409


@pytest.mark.anyio
async def test_new_resources_are_denied_across_company_boundaries(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    enabled = settings.model_copy(update={"demo_tools_enabled": True})
    async with ai_api_client(enabled, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="scope-owner@example.com",
        )
        outsider = await _other_company_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="scope-outsider@example.com",
        )
        factory, machine, sensor = await _hierarchy(
            session_factory, "scope-owner@example.com"
        )
        uploaded = await client.post(
            "/data-onboarding/imports",
            headers={**owner, "Idempotency-Key": "scope-import-001"},
            files={
                "file": (
                    "scope.csv",
                    "timestamp,machine,sensor,value\n"
                    f"2026-07-24T10:00:00Z,{machine.name},{sensor.name},1\n",
                    "text/csv",
                )
            },
        )
        assert uploaded.status_code == 201
        report = await client.post(
            "/reporting/reports",
            headers=owner,
            json={
                "report_type": "executive_factory_summary",
                "format": "csv",
                "factory_id": str(factory.id),
                "period_start": (utc_now() - timedelta(days=1)).isoformat(),
                "period_end": utc_now().isoformat(),
                "idempotency_key": "scope-report-001",
            },
        )
        assert report.status_code == 201
        run = await client.post(
            "/demo/runs",
            headers=owner,
            json={
                "factory_id": str(factory.id),
                "machine_id": str(machine.id),
                "scenario": "normal_operation",
                "speed": 1,
                "idempotency_key": "scope-demo-001",
            },
        )
        assert run.status_code == 201
        layout = await client.put(
            f"/demo/factories/{factory.id}/layout",
            headers=owner,
            json={"nodes": [{"machine_id": str(machine.id), "x": 10, "y": 20}]},
        )
        assert layout.status_code == 200

        for path in (
            f"/data-onboarding/imports/{uploaded.json()['id']}",
            f"/reporting/reports/{report.json()['id']}",
            f"/demo/runs/{run.json()['id']}",
            f"/demo/factories/{factory.id}/layout",
        ):
            denied = await client.get(path, headers=outsider)
            assert denied.status_code == 404, (path, denied.text)


def test_export_helpers_prevent_formula_execution_and_emit_valid_signatures() -> None:
    assert spreadsheet_safe("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    workbook = xlsx_report(
        {
            "Summary": [
                {
                    "captured_at": datetime(2026, 7, 24, tzinfo=UTC),
                    "value": "=2+2",
                }
            ]
        }
    )
    assert workbook.startswith(b"PK")
    with ZipFile(BytesIO(workbook)) as archive:
        worksheet = archive.read("xl/worksheets/sheet1.xml").decode()
        assert "'=2+2" in worksheet
        assert 's="1"' in worksheet
        assert 's="2"' in worksheet
        assert "<autoFilter " in worksheet
        assert 'state="frozen"' in worksheet
        assert "xl/styles.xml" in archive.namelist()
    report = pdf_report(
        "Report",
        ["Safe content"],
        chart_values=[("alerts", 2)],
        metadata=(("Company", "FK Manufacturing"),),
    )
    assert report.startswith(b"%PDF-")
    assert len(report) > 1_500
    assert b"Key metrics chart" in report
    assert b"Company: FK Manufacturing" in report
    assert b"Alerts" in report
    assert b"Page 1 of 1" in report
    assert b"0 0 595 842 re f" in report
    assert b" re f" in report


def test_sprints_3_5_migrations_upgrade_downgrade_and_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "sprints-3-5.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "sprints-3-5-migration-secret-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "0017_add_alert_shift_workflow")
    command.upgrade(config, "head")
    command.downgrade(config, "0017_add_alert_shift_workflow")
    command.upgrade(config, "head")
    command.check(config)
    get_settings.cache_clear()

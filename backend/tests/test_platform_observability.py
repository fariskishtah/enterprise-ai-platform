"""FastAPI Prometheus endpoint, normalization, and failure-isolation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import app.observability.metrics as metrics_module
import pytest
from app.config.settings import Settings
from app.core.application import create_app
from app.observability.metrics import (
    HTTP_REQUESTS,
    TRAINING_JOBS_SUBMITTED,
    configure_metrics,
    record_monitoring_evaluation,
    record_prediction,
    record_training_job_submitted,
)
from httpx import ASGITransport, AsyncClient


def _observability_settings(
    settings: Settings, *, service: str, enabled: bool = True
) -> Settings:
    return settings.model_copy(
        update={
            "observability_metrics_enabled": enabled,
            "observability_service_name": service,
            "observability_environment": "test",
        }
    )


@asynccontextmanager
async def _client(settings: Settings) -> AsyncIterator[AsyncClient]:
    application = create_app(settings)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_metrics_endpoint_is_enabled_and_requires_no_authentication(
    settings: Settings,
) -> None:
    configured = _observability_settings(settings, service="metrics-enabled-test")
    async with _client(configured) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert "training_jobs_submitted_total" in response.text


@pytest.mark.anyio
async def test_metrics_endpoint_can_be_disabled(settings: Settings) -> None:
    configured = _observability_settings(
        settings,
        service="metrics-disabled-test",
        enabled=False,
    )
    async with _client(configured) as client:
        response = await client.get("/metrics")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_http_metrics_use_route_templates_and_exclude_noisy_paths(
    settings: Settings,
) -> None:
    configured = _observability_settings(settings, service="route-template-test")
    application = create_app(configured)

    async def probe(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    application.add_api_route(
        "/observability-probe/{item_id}",
        probe,
        methods=["GET"],
    )
    transport = ASGITransport(app=application)
    raw_identifier = "private-value-123"
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        assert (
            await client.get(f"/observability-probe/{raw_identifier}")
        ).status_code == 200
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/docs")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200
        metrics = await client.get("/metrics")

    assert 'route="/observability-probe/{item_id}"' in metrics.text
    assert raw_identifier not in metrics.text
    assert 'route="/health"' not in metrics.text
    assert 'route="/docs"' not in metrics.text
    assert 'route="/openapi.json"' not in metrics.text
    assert 'route="/metrics"' not in metrics.text


def test_custom_metric_recorders_increment_bounded_series() -> None:
    configure_metrics(
        enabled=True,
        service="custom-counter-test",
        environment="test",
    )
    submitted = _submitted_value()

    record_training_job_submitted(
        task_type="regression",
        algorithm="random_forest",
    )
    record_prediction(
        task_type="regression",
        algorithm="random_forest",
        final_status="succeeded",
        row_count=4,
    )
    record_monitoring_evaluation(
        trigger="manual",
        final_status="healthy",
        duration_seconds=0.25,
    )

    assert _submitted_value() == submitted + 1


def _submitted_value() -> float:
    counter = TRAINING_JOBS_SUBMITTED.labels(
        service="custom-counter-test",
        environment="test",
        task_type="regression",
        algorithm="random_forest",
    )
    return next(
        sample.value
        for metric in counter.collect()
        for sample in metric.samples
        if sample.name == "training_jobs_submitted_total"
    )


@pytest.mark.anyio
async def test_metric_collection_failure_does_not_break_http_operation(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _observability_settings(settings, service="metric-failure-test")

    def fail_labels(**labels: str) -> None:
        _ = labels
        raise RuntimeError("metric backend unavailable")

    warnings: list[tuple[str, tuple[object, ...]]] = []

    def capture_warning(message: str, *arguments: object) -> None:
        warnings.append((message, arguments))

    monkeypatch.setattr(HTTP_REQUESTS, "labels", fail_labels)
    monkeypatch.setattr(metrics_module.logger, "warning", capture_warning)
    application = create_app(configured)

    async def business_probe() -> dict[str, str]:
        return {"status": "preserved"}

    application.add_api_route("/business-probe", business_probe, methods=["GET"])
    transport = ASGITransport(app=application)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/business-probe")

    assert response.status_code == 200
    assert response.json() == {"status": "preserved"}
    assert warnings == [
        (
            "observability_metric_collection_failed metric_name=%s",
            ("http_requests_total",),
        )
    ]


def test_metrics_route_does_not_change_openapi(settings: Settings) -> None:
    schema = create_app(
        _observability_settings(settings, service="openapi-metrics-test")
    ).openapi()

    assert "/health" in schema["paths"]
    assert "/metrics" not in schema["paths"]

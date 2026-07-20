"""Structured logging, request context, and worker propagation tests."""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import app.observability.request_logging as request_logging_module
import pytest
from app.config.settings import Settings
from app.core.application import create_app
from app.observability.logging import (
    SafeJsonFormatter,
    bind_log_context,
    configure_logging,
    current_correlation_id,
    current_request_id,
    emit_safe,
    reset_log_context,
    sanitize_log_text,
)
from app.observability.worker_logging import WorkerLoggingMiddleware, worker_job_name
from dramatiq import Message
from dramatiq.broker import Broker, MessageProxy
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@asynccontextmanager
async def _client(
    settings: Settings, *, raise_app_exceptions: bool = True
) -> AsyncIterator[tuple[AsyncClient, object]]:
    application = create_app(settings)
    transport = ASGITransport(
        app=application,
        raise_app_exceptions=raise_app_exceptions,
    )
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, application


def _configure_stream(stream: io.StringIO, *, log_format: str = "json") -> None:
    configure_logging(
        enabled=True,
        log_format=cast("object", log_format),
        log_level="INFO",
        service="logging-test",
        environment="test",
        access_logging_enabled=True,
        stream=stream,
    )


def test_json_formatter_emits_stable_schema_and_redacts_sensitive_values() -> None:
    stream = io.StringIO()
    _configure_stream(stream)
    tokens = bind_log_context(
        request_id="request-safe",
        correlation_id="correlation-safe",
    )
    logger = logging.getLogger("test.privacy")
    secret_uuid = "f62ba57c-c802-4ef1-8b91-e4d9dde31f9d"
    try:
        try:
            raise RuntimeError("password=raw-secret user@example.com")
        except RuntimeError:
            emit_safe(
                logger,
                logging.ERROR,
                (
                    "Authorization: Bearer token-value "
                    f"email=user@example.com id={secret_uuid} features=[1,2,3]"
                ),
                extra={
                    "job_name": "training",
                    "attempt_number": 2,
                    "not_allowlisted": "must-not-appear",
                },
                exc_info=True,
            )
    finally:
        reset_log_context(tokens)

    payload = json.loads(stream.getvalue())
    assert payload["service"] == "logging-test"
    assert payload["environment"] == "test"
    assert payload["request_id"] == "request-safe"
    assert payload["correlation_id"] == "correlation-safe"
    assert payload["trace_id"] is None
    assert payload["job_name"] == "training"
    assert payload["attempt_number"] == 2
    assert payload["exception"]["type"] == "RuntimeError"
    assert payload["exception"]["stack"]
    rendered = json.dumps(payload)
    for sensitive in (
        "token-value",
        "raw-secret",
        "user@example.com",
        secret_uuid,
        "[1,2,3]",
        "must-not-appear",
    ):
        assert sensitive not in rendered


def test_formatter_failure_returns_valid_fallback_json() -> None:
    class BrokenMessage:
        def __str__(self) -> str:
            raise RuntimeError("unsafe-value")

    record = logging.LogRecord(
        name="test.formatter",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=BrokenMessage(),
        args=(),
        exc_info=None,
    )
    payload = json.loads(SafeJsonFormatter().format(record))

    assert payload["message"] == "log_message_unavailable"
    assert "unsafe-value" not in json.dumps(payload)


def test_log_sanitizer_redacts_authentication_and_session_material() -> None:
    """Headers, JSON credentials, API keys, and session IDs are redacted."""
    sensitive_values = (
        "authorization-secret",
        "cookie-secret",
        "set-cookie-secret",
        "password-secret",
        "access-secret",
        "refresh-secret",
        "api-secret",
        "session-secret",
    )
    message = "\n".join(
        (
            f"Authorization: Bearer {sensitive_values[0]}",
            f"Cookie: session={sensitive_values[1]}",
            f"Set-Cookie: session={sensitive_values[2]}",
            f'{{"password":"{sensitive_values[3]}"}}',
            f"access_token={sensitive_values[4]}",
            f'refresh-token="{sensitive_values[5]}"',
            f"X-API-Key: {sensitive_values[6]}",
            f'session_id="{sensitive_values[7]}"',
        )
    )

    rendered = sanitize_log_text(message)

    assert rendered.count("[REDACTED]") == len(sensitive_values)
    for sensitive in sensitive_values:
        assert sensitive not in rendered


def test_text_format_and_log_level_are_configurable() -> None:
    stream = io.StringIO()
    configure_logging(
        enabled=True,
        log_format="text",
        log_level="WARNING",
        service="text-test",
        environment="test",
        access_logging_enabled=True,
        stream=stream,
    )
    logger = logging.getLogger("test.text")
    logger.info("not_emitted")
    logger.warning("safe_text_message")

    output = stream.getvalue()
    assert "not_emitted" not in output
    assert "safe_text_message" in output
    assert not output.lstrip().startswith("{")


def test_logging_settings_reject_invalid_headers_and_levels(settings: Settings) -> None:
    values = settings.model_dump()
    values["request_id_header"] = "bad header"
    with pytest.raises(ValidationError):
        Settings.model_validate(values)

    values = settings.model_dump()
    values["log_level"] = "TRACE"
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_logging_setting_defaults_match_container_contract(settings: Settings) -> None:
    assert settings.structured_logging_enabled is True
    assert settings.log_format == "json"
    assert settings.log_level == "INFO"
    assert settings.http_access_logging_enabled is True
    assert settings.request_id_header == "X-Request-ID"
    assert settings.correlation_id_header == "X-Correlation-ID"
    assert settings.log_service_name == "ai-manufacturing-backend"
    assert settings.log_environment == "local"


@pytest.mark.anyio
async def test_request_ids_are_validated_returned_and_context_is_cleared(
    settings: Settings,
) -> None:
    async with _client(settings) as (client, _application):
        response = await client.get(
            "/health",
            headers={
                "X-Request-ID": "invalid id with spaces",
                "X-Correlation-ID": "x" * 129,
            },
        )
        accepted = await client.get(
            "/health",
            headers={
                "X-Request-ID": "request.accepted-1",
                "X-Correlation-ID": "correlation:accepted-1",
            },
        )

    generated_request = response.headers["X-Request-ID"]
    assert _SAFE_ID.fullmatch(generated_request)
    assert response.headers["X-Correlation-ID"] == generated_request
    assert accepted.headers["X-Request-ID"] == "request.accepted-1"
    assert accepted.headers["X-Correlation-ID"] == "correlation:accepted-1"
    assert current_request_id() is None
    assert current_correlation_id() is None


@pytest.mark.anyio
async def test_access_log_uses_route_template_and_omits_request_data(
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    application = create_app(settings)

    async def probe(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    application.add_api_route("/logging-probe/{item_id}", probe, methods=["POST"])
    transport = ASGITransport(app=application)
    private_value = "private-path-value"
    body_secret = "body-secret-value"
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/logging-probe/{private_value}?token=query-secret-value",
            headers={"Authorization": "Bearer header-secret-value"},
            content=body_secret,
        )

    records = [record for record in caplog.records if record.name == "app.access"]
    assert response.status_code == 200
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "http_request_completed"
    assert record.method == "POST"
    assert record.normalized_route == "/logging-probe/{item_id}"
    assert record.status_code == 200
    assert record.duration_ms >= 0
    rendered = " ".join(item.getMessage() for item in records)
    for sensitive in (
        private_value,
        "query-secret-value",
        "header-secret-value",
        body_secret,
    ):
        assert sensitive not in rendered


@pytest.mark.anyio
async def test_access_logging_excludes_noisy_paths(
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(settings) as (client, _application):
        for path in ("/health", "/metrics", "/docs", "/openapi.json"):
            assert (await client.get(path)).status_code == 200

    assert not [record for record in caplog.records if record.name == "app.access"]


@pytest.mark.anyio
async def test_logging_failure_and_request_exception_do_not_leak_context(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_logging(*args: object, **kwargs: object) -> None:
        _ = (args, kwargs)
        raise RuntimeError("logger unavailable")

    monkeypatch.setattr(request_logging_module, "emit_safe", fail_logging)
    application = create_app(settings)

    async def success() -> dict[str, str]:
        return {"status": "preserved"}

    async def failure() -> None:
        raise RuntimeError("private exception value")

    application.add_api_route("/logging-success", success, methods=["GET"])
    application.add_api_route("/logging-failure", failure, methods=["GET"])
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        success_response = await client.get("/logging-success")
        failure_response = await client.get("/logging-failure")

    assert success_response.status_code == 200
    assert success_response.json() == {"status": "preserved"}
    assert failure_response.status_code == 500
    assert current_request_id() is None
    assert current_correlation_id() is None


def test_worker_propagates_only_safe_correlation_and_logs_lifecycle() -> None:
    stream = io.StringIO()
    _configure_stream(stream)
    middleware = WorkerLoggingMiddleware(
        enabled=True,
        log_format="json",
        log_level="INFO",
        service="worker-test",
        environment="test",
    )
    message = Message(
        queue_name="test",
        actor_name="execute_training_job",
        args=("private-job-argument",),
        kwargs={},
        options={"retries": 1},
        message_id="message-id",
    )
    broker = cast("Broker", object())
    tokens = bind_log_context(
        request_id="web-request",
        correlation_id="web-correlation",
    )
    try:
        middleware.before_enqueue(broker, message, delay=0)
    finally:
        reset_log_context(tokens)

    assert message.options == {"retries": 1, "correlation_id": "web-correlation"}
    proxy = MessageProxy(message)
    middleware.before_process_message(broker, proxy)
    assert current_request_id() is None
    assert current_correlation_id() == "web-correlation"
    middleware.after_process_message(
        broker,
        proxy,
        exception=RuntimeError("secret@example.com password=worker-secret"),
    )

    assert current_correlation_id() is None
    payloads = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [payload["lifecycle_status"] for payload in payloads] == [
        "started",
        "failed",
    ]
    assert all(payload["job_name"] == "training" for payload in payloads)
    assert all(payload["attempt_number"] == 2 for payload in payloads)
    rendered = json.dumps(payloads)
    assert "private-job-argument" not in rendered
    assert "secret@example.com" not in rendered
    assert "worker-secret" not in rendered


def test_worker_keeps_valid_retry_correlation_and_maps_all_actors() -> None:
    middleware = WorkerLoggingMiddleware(
        enabled=True,
        log_format="json",
        log_level="INFO",
        service="worker-test",
        environment="test",
    )
    message = Message(
        queue_name="test",
        actor_name="execute_scheduled_monitoring",
        args=(),
        kwargs={},
        options={"correlation_id": "retry-correlation"},
    )
    middleware.before_enqueue(cast("Broker", object()), message, delay=10)

    assert message.options == {"correlation_id": "retry-correlation"}
    assert {
        worker_job_name(name)
        for name in (
            "execute_training_job",
            "execute_scheduled_monitoring",
            "execute_prediction_event_retention",
            "execute_monitoring_evaluation_retention",
            "execute_reference_profile_reconciliation",
            "execute_retraining_reconciliation",
            "execute_stale_alert_reconciliation",
        )
    } == {
        "training",
        "monitoring_evaluation",
        "prediction_event_retention",
        "monitoring_evaluation_retention",
        "reference_profile_reconciliation",
        "retraining_reconciliation",
        "stale_alert_reconciliation",
    }

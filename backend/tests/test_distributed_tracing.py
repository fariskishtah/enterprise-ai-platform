"""Focused privacy, propagation, and correlation tests for distributed tracing."""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

import pytest
from app.config.settings import Settings
from app.observability.logging import configure_logging, emit_safe
from app.observability.tracing import (
    FastAPITracingMiddleware,
    TracingConfig,
    TracingConfigurator,
    current_span_id,
    current_trace_id,
    start_domain_span,
    start_dramatiq_producer_span,
)
from app.observability.worker_logging import WorkerLoggingMiddleware
from dramatiq import Message
from dramatiq.broker import Broker, MessageProxy
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState
from pydantic import ValidationError

_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")


@dataclass(frozen=True)
class _TracingHarness:
    provider: TracerProvider
    exporter: InMemorySpanExporter


@pytest.fixture
def tracing_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[_TracingHarness]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        trace,
        "get_tracer",
        lambda *_args, **_kwargs: provider.get_tracer("test-platform"),
    )
    try:
        yield _TracingHarness(provider=provider, exporter=exporter)
    finally:
        provider.shutdown()


def _config(*, enabled: bool = True) -> TracingConfig:
    return TracingConfig(
        enabled=enabled,
        service_name="test-backend",
        service_namespace="test-platform",
        environment="test",
        service_version="0.8.0",
        otlp_endpoint="http://tempo:4317",
        otlp_insecure=True,
        sampler="parentbased_traceidratio",
        sampler_arg=1.0,
    )


def _worker_middleware() -> WorkerLoggingMiddleware:
    return WorkerLoggingMiddleware(
        enabled=True,
        log_format="json",
        log_level="INFO",
        service="test-worker",
        environment="test",
    )


def _finished_spans(harness: _TracingHarness) -> tuple[ReadableSpan, ...]:
    return harness.exporter.get_finished_spans()


def test_tracing_disabled_and_idempotent_initialization() -> None:
    disabled = TracingConfigurator()
    assert disabled.configure(_config(enabled=False), install_global=False) is None
    assert disabled.runtime is None

    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    configurator = TracingConfigurator()
    first = configurator.configure(
        _config(),
        install_global=False,
        instrument_libraries=False,
        span_processor=processor,
    )
    second = configurator.configure(
        _config(),
        install_global=False,
        instrument_libraries=False,
        span_processor=processor,
    )

    assert first is not None
    assert second is first
    assert configurator.runtime is first
    first.provider.shutdown()


@pytest.mark.usefixtures("tracing_harness")
def test_trace_identifiers_and_json_logs_follow_only_active_span() -> None:
    stream = io.StringIO()
    configure_logging(
        enabled=True,
        log_format="json",
        log_level="INFO",
        service="trace-log-test",
        environment="test",
        access_logging_enabled=True,
        stream=stream,
    )
    logger = logging.getLogger("test.trace-logging")

    assert current_trace_id() is None
    assert current_span_id() is None
    emit_safe(logger, logging.INFO, "outside_span")
    with trace.get_tracer("test").start_as_current_span("inside"):
        active_trace_id = current_trace_id()
        active_span_id = current_span_id()
        emit_safe(logger, logging.INFO, "inside_span")

    payloads = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert payloads[0]["trace_id"] is None
    assert _TRACE_ID.fullmatch(cast(str, active_trace_id))
    assert _SPAN_ID.fullmatch(cast(str, active_span_id))
    assert payloads[1]["trace_id"] == active_trace_id
    assert current_trace_id() is None


def test_unsampled_valid_span_still_exposes_trace_identity() -> None:
    span_context = SpanContext(
        trace_id=0x1234,
        span_id=0x5678,
        is_remote=True,
        trace_flags=TraceFlags(0),
        trace_state=TraceState(),
    )

    with trace.use_span(NonRecordingSpan(span_context), end_on_exit=False):
        assert current_trace_id() == "00000000000000000000000000001234"
        assert current_span_id() == "0000000000005678"

    assert current_trace_id() is None


@pytest.mark.anyio
async def test_fastapi_spans_use_templates_and_omit_request_data(
    tracing_harness: _TracingHarness,
) -> None:
    application = FastAPI()

    @application.post("/widgets/{widget_id}")
    async def create_widget(widget_id: str, request: Request) -> dict[str, str]:
        _ = await request.body()
        return {"widget_id": widget_id}

    application.add_middleware(FastAPITracingMiddleware, enabled=True)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/widgets/private-path?token=private-query",
            headers={
                "Authorization": "Bearer private-header",
                "Cookie": "session=private-cookie",
            },
            content="private-body",
        )

    spans = _finished_spans(tracing_harness)
    assert response.status_code == 200
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "POST /widgets/{widget_id}"
    assert span.attributes == {
        "http.request.method": "POST",
        "http.route": "/widgets/{widget_id}",
        "http.response.status_code": 200,
    }
    rendered = f"{span.name} {span.attributes} {span.events}"
    for sensitive in (
        "private-path",
        "private-query",
        "private-header",
        "private-cookie",
        "private-body",
    ):
        assert sensitive not in rendered


@pytest.mark.anyio
async def test_fastapi_trace_exclusions(
    tracing_harness: _TracingHarness,
) -> None:
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    for excluded_path in ("/health", "/metrics", "/docs", "/openapi.json", "/redoc"):
        application.add_api_route(
            excluded_path,
            lambda: {"status": "ok"},
            methods=["GET"],
        )
    application.add_middleware(FastAPITracingMiddleware, enabled=True)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for excluded_path in (
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        ):
            assert (await client.get(excluded_path)).status_code == 200

    assert _finished_spans(tracing_harness) == ()


def test_dramatiq_w3c_parent_child_continuity_and_retry_preservation(
    tracing_harness: _TracingHarness,
) -> None:
    middleware = _worker_middleware()
    broker = cast("Broker", object())
    message: Message[object] = Message(
        queue_name="ai-training",
        actor_name="execute_training_job",
        args=("private-job-id",),
        kwargs={},
        options={"correlation_id": "tracing-correlation-123"},
        message_id="message-1",
    )
    tracer = trace.get_tracer("test")

    with tracer.start_as_current_span("api-request") as request_span:
        request_trace_id = request_span.get_span_context().trace_id
        with start_dramatiq_producer_span("training"):
            middleware.before_enqueue(broker, message, delay=0)

    carrier = message.options["otel_trace_context"]
    assert isinstance(carrier, dict)
    assert set(carrier) <= {"traceparent", "tracestate"}
    assert re.fullmatch(
        r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}",
        cast(str, carrier["traceparent"]),
    )

    proxy = MessageProxy(message)
    middleware.before_process_message(broker, proxy)
    assert int(cast(str, current_trace_id()), 16) == request_trace_id
    with start_domain_span(
        "training.execution",
        attributes={"algorithm": "random_forest", "job_id": "must-drop"},
    ):
        pass
    middleware.after_process_message(broker, proxy)

    spans = {span.name: span for span in _finished_spans(tracing_harness)}
    producer = spans["dramatiq training publish"]
    consumer = spans["dramatiq training process"]
    business = spans["training.execution"]
    assert producer.parent is not None
    assert producer.parent.span_id == spans["api-request"].context.span_id
    assert consumer.parent is not None
    assert consumer.parent.span_id == producer.context.span_id
    assert business.parent is not None
    assert business.parent.span_id == consumer.context.span_id
    assert business.attributes == {"algorithm": "random_forest"}
    assert len({span.context.trace_id for span in spans.values()}) == 1

    original_carrier = dict(cast(dict[str, str], carrier))
    middleware.before_enqueue(broker, message, delay=1000)
    assert message.options["otel_trace_context"] == original_carrier


def test_invalid_dramatiq_trace_context_fails_safe(
    tracing_harness: _TracingHarness,
) -> None:
    middleware = _worker_middleware()
    broker = cast("Broker", object())
    message: Message[object] = Message(
        queue_name="ai-monitoring",
        actor_name="execute_scheduled_monitoring",
        args=(),
        kwargs={},
        options={
            "correlation_id": "independent-correlation",
            "otel_trace_context": {
                "traceparent": "not-valid",
                "authorization": "must-not-propagate",
            },
        },
        message_id="message-invalid",
    )
    proxy = MessageProxy(message)

    middleware.before_process_message(broker, proxy)
    generated_trace_id = current_trace_id()
    middleware.after_process_message(
        broker,
        proxy,
        exception=RuntimeError("password=must-not-export"),
    )

    assert _TRACE_ID.fullmatch(cast(str, generated_trace_id))
    span = _finished_spans(tracing_harness)[0]
    assert span.parent is None
    rendered = f"{span.attributes} {span.events} {span.status}"
    assert "must-not-export" not in rendered
    assert "authorization" not in rendered


def test_tracing_settings_are_typed_and_reject_credentialed_endpoint(
    settings: Settings,
) -> None:
    configured = settings.model_copy(update={"tracing_enabled": True})
    assert configured.otel_service_name == "ai-manufacturing-backend"
    assert configured.otel_worker_service_name == "ai-manufacturing-training-worker"
    assert configured.otel_traces_sampler == "parentbased_traceidratio"
    assert configured.otel_traces_sampler_arg == 1.0

    values = configured.model_dump()
    values["otel_exporter_otlp_endpoint"] = "http://user:secret@tempo:4317"
    with pytest.raises(ValidationError):
        Settings.model_validate(values)

"""Privacy-preserving OpenTelemetry tracing for API and worker processes."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from threading import Lock
from typing import Any, Final, ParamSpec, Protocol, TypeVar

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

_INSTRUMENTATION_NAME: Final = "ai-manufacturing-platform"
_TRACE_HEADER_NAMES: Final = frozenset({b"traceparent", b"tracestate"})
_SAFE_ROUTE_PATTERN: Final = re.compile(r"^/[A-Za-z0-9_{}./:-]{0,255}$")
_SAFE_METHOD_PATTERN: Final = re.compile(r"^[A-Z]{1,16}$")
_SAFE_ATTRIBUTE_PATTERN: Final = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_DOMAIN_ATTRIBUTE_NAMES: Final = frozenset(
    {
        "algorithm",
        "task_type",
        "lifecycle_status",
        "trigger",
        "alert_type",
        "severity",
        "outcome",
    }
)
_EXCLUDED_TRACE_PATHS: Final = frozenset(
    {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}
)

P = ParamSpec("P")
R = TypeVar("R")


class _ExporterFactory(Protocol):
    def __call__(self, *, endpoint: str, insecure: bool) -> SpanExporter: ...


@dataclass(frozen=True)
class TracingConfig:
    """Bounded process-level tracing configuration."""

    enabled: bool
    service_name: str
    service_namespace: str
    environment: str
    service_version: str
    otlp_endpoint: str
    otlp_insecure: bool
    sampler: str
    sampler_arg: float


@dataclass(frozen=True)
class TracingRuntime:
    """The provider installed by one process-local configuration pass."""

    config: TracingConfig
    provider: TracerProvider


class TracingConfigurator:
    """Idempotently construct a provider without hiding initialization failures."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._runtime: TracingRuntime | None = None

    @property
    def runtime(self) -> TracingRuntime | None:
        return self._runtime

    def configure(
        self,
        config: TracingConfig,
        *,
        install_global: bool = True,
        instrument_libraries: bool = True,
        exporter_factory: _ExporterFactory = OTLPSpanExporter,
        span_processor: SpanProcessor | None = None,
    ) -> TracingRuntime | None:
        """Install tracing once, or return ``None`` in disabled/failed mode."""
        if not config.enabled:
            return None
        with self._lock:
            if self._runtime is not None:
                return self._runtime
            try:
                if config.sampler != "parentbased_traceidratio":
                    raise ValueError("unsupported tracing sampler")
                provider = TracerProvider(
                    resource=Resource.create(
                        {
                            "service.name": config.service_name,
                            "service.namespace": config.service_namespace,
                            "service.version": config.service_version,
                            "deployment.environment.name": config.environment,
                        }
                    ),
                    sampler=ParentBased(TraceIdRatioBased(config.sampler_arg)),
                )
                processor = span_processor
                if processor is None:
                    exporter = exporter_factory(
                        endpoint=config.otlp_endpoint,
                        insecure=config.otlp_insecure,
                    )
                    processor = BatchSpanProcessor(exporter)
                provider.add_span_processor(processor)
                if install_global:
                    reset_global_propagator_to_trace_context()
                    trace.set_tracer_provider(provider)
                runtime = TracingRuntime(config=config, provider=provider)
                self._runtime = runtime
                if install_global and instrument_libraries:
                    _instrument_client_libraries(provider)
                return runtime
            except Exception:
                logger.error("tracing_initialization_failed", exc_info=True)
                return None


_process_configurator = TracingConfigurator()


def configure_tracing(config: TracingConfig) -> TracingRuntime | None:
    """Configure the process-global tracing runtime once."""
    return _process_configurator.configure(config)


def current_trace_id() -> str | None:
    """Return the current valid trace ID as 32 lowercase hexadecimal digits."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}"


def current_span_id() -> str | None:
    """Return the current valid span ID as 16 lowercase hexadecimal digits."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.span_id:016x}"


def record_safe_span_error(span: Span, exception: BaseException) -> None:
    """Mark an error using its bounded type only, never its value or traceback."""
    span.set_status(Status(StatusCode.ERROR))
    span.add_event(
        "exception",
        attributes={"exception.type": type(exception).__name__[:128]},
    )


@contextmanager
def start_domain_span(
    name: str,
    *,
    attributes: Mapping[str, str] | None = None,
) -> Iterator[Span]:
    """Create one meaningful internal span with a strict attribute vocabulary."""
    safe_attributes = _safe_domain_attributes(attributes or {})
    tracer = trace.get_tracer(_INSTRUMENTATION_NAME)
    with tracer.start_as_current_span(
        name,
        kind=SpanKind.INTERNAL,
        attributes=safe_attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as exception:
            record_safe_span_error(span, exception)
            raise


@contextmanager
def start_dramatiq_producer_span(job_name: str) -> Iterator[Span]:
    """Trace the complete broker enqueue so its Redis call is a child span."""
    safe_job_name = (
        job_name
        if _SAFE_ATTRIBUTE_PATTERN.fullmatch(job_name) is not None
        else "unknown"
    )
    tracer = trace.get_tracer(_INSTRUMENTATION_NAME)
    with tracer.start_as_current_span(
        f"dramatiq {safe_job_name} publish",
        kind=SpanKind.PRODUCER,
        attributes={
            "messaging.system": "dramatiq",
            "messaging.operation.type": "publish",
            "messaging.destination.name": safe_job_name,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as exception:
            record_safe_span_error(span, exception)
            raise


def traced_operation(
    name: str,
    *,
    attributes: Mapping[str, str] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Trace a synchronous actor body without adding message arguments to spans."""

    def decorate(operation: Callable[P, R]) -> Callable[P, R]:
        @wraps(operation)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with start_domain_span(name, attributes=attributes):
                return operation(*args, **kwargs)

        return wrapped

    return decorate


def traced_async_operation(
    name: str,
    *,
    attributes: Mapping[str, str] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Trace an async business operation without inspecting its arguments."""

    def decorate(operation: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(operation)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with start_domain_span(name, attributes=attributes):
                return await operation(*args, **kwargs)

        return wrapped

    return decorate


class FastAPITracingMiddleware:
    """Controlled ASGI server tracing with route templates and no payload capture."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        excluded_paths: frozenset[str] = _EXCLUDED_TRACE_PATHS,
    ) -> None:
        self._app = app
        self._enabled = enabled
        self._excluded_paths = excluded_paths
        self._tracer = trace.get_tracer(_INSTRUMENTATION_NAME)
        self._propagator = TraceContextTextMapPropagator()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            not self._enabled
            or scope["type"] != "http"
            or scope.get("path") in self._excluded_paths
        ):
            await self._app(scope, receive, send)
            return

        method = _safe_method(scope.get("method"))
        parent_context = self._propagator.extract(
            carrier=_trace_headers(scope),
        )
        status_code: int | None = None

        async def traced_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                candidate = message.get("status")
                if isinstance(candidate, int):
                    status_code = candidate
            await send(message)

        with self._tracer.start_as_current_span(
            f"{method} unmatched",
            context=parent_context,
            kind=SpanKind.SERVER,
            attributes={"http.request.method": method},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                await self._app(scope, receive, traced_send)
            except BaseException as exception:
                record_safe_span_error(span, exception)
                raise
            finally:
                route = _normalized_route(scope)
                if route is not None:
                    span.update_name(f"{method} {route}")
                    span.set_attribute("http.route", route)
                if status_code is not None:
                    span.set_attribute("http.response.status_code", status_code)
                    if status_code >= 500:
                        span.set_status(Status(StatusCode.ERROR))


def inject_w3c_trace_context(carrier: MutableMapping[str, str]) -> None:
    """Inject only W3C trace-context fields into a mutable string carrier."""
    TraceContextTextMapPropagator().inject(carrier=carrier)
    for key in tuple(carrier):
        if key not in {"traceparent", "tracestate"}:
            del carrier[key]


def extract_w3c_trace_context(carrier: Mapping[str, str]) -> Any:
    """Extract W3C context; malformed input safely produces an empty context."""
    return TraceContextTextMapPropagator().extract(carrier=carrier)


def _instrument_client_libraries(provider: TracerProvider) -> None:
    try:
        SQLAlchemyInstrumentor().instrument(
            tracer_provider=provider,
            enable_commenter=False,
            enable_attribute_commenter=False,
        )
    except Exception:
        logger.error("sqlalchemy_tracing_initialization_failed", exc_info=True)
    try:
        _disable_redis_search_enrichment()
        RedisInstrumentor().instrument(tracer_provider=provider)
    except Exception:
        logger.error("redis_tracing_initialization_failed", exc_info=True)


def _disable_redis_search_enrichment() -> None:
    """Prevent optional Redis Search hooks from attaching query/index values."""
    import opentelemetry.instrumentation.redis as redis_instrumentation

    def no_enrichment(*args: object, **kwargs: object) -> None:
        _ = (args, kwargs)

    redis_instrumentation.__dict__["_add_create_attributes"] = no_enrichment
    redis_instrumentation.__dict__["_add_search_attributes"] = no_enrichment


def _safe_domain_attributes(attributes: Mapping[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in attributes.items():
        if (
            key in _DOMAIN_ATTRIBUTE_NAMES
            and isinstance(value, str)
            and _SAFE_ATTRIBUTE_PATTERN.fullmatch(value) is not None
        ):
            safe[key] = value
    return safe


def _safe_method(value: object) -> str:
    if isinstance(value, str):
        candidate = value.upper()
        if _SAFE_METHOD_PATTERN.fullmatch(candidate) is not None:
            return candidate
    return "OTHER"


def _normalized_route(scope: Scope) -> str | None:
    route_object = scope.get("route")
    route = getattr(route_object, "path", None)
    if isinstance(route, str) and _SAFE_ROUTE_PATTERN.fullmatch(route) is not None:
        return route
    return None


def _trace_headers(scope: Scope) -> dict[str, str]:
    carrier: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.lower()
        if name not in _TRACE_HEADER_NAMES or len(raw_value) > 512:
            continue
        try:
            carrier[name.decode("ascii")] = raw_value.decode("ascii")
        except UnicodeDecodeError:
            continue
    return carrier


def reset_global_propagator_to_trace_context() -> None:
    """Keep baggage out of platform-controlled process propagation."""
    propagate.set_global_textmap(TraceContextTextMapPropagator())

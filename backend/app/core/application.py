"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config.settings import Settings, get_settings
from app.core.security_headers import SecurityHeadersMiddleware
from app.observability import (
    FastAPITracingMiddleware,
    PrometheusMetricsMiddleware,
    RequestContextLoggingMiddleware,
    TracingConfig,
    configure_logging,
    configure_metrics,
    configure_tracing,
    metrics_response,
)

OPENAPI_TAGS = [
    {
        "name": "ai",
        "description": (
            "Authenticated synchronous and Redis-backed background Random Forest "
            "training, MLflow registration, controlled alias promotion, audit "
            "history, version lookup, registered prediction, and privacy-preserving "
            "prediction monitoring."
        ),
    },
    {
        "name": "ai-monitoring",
        "description": (
            "Authorized prediction-event summaries, exact-version operational and "
            "data-quality metrics, evaluation reference profiles, and bounded "
            "feature/prediction drift reports."
        ),
    },
    {
        "name": "ai-retraining",
        "description": (
            "Explicit controlled retraining policies, audited drift decisions, "
            "persisted cooldown and quota state, trusted source-job lineage, "
            "background candidate creation, and advisory metric comparison."
        ),
    },
    {"name": "auth", "description": "Authentication and token management."},
    {"name": "companies", "description": "Company management."},
    {"name": "feature-datasets", "description": "Feature dataset exports."},
    {"name": "factories", "description": "Factory management."},
    {"name": "health", "description": "Service health checks."},
    {"name": "machines", "description": "Machine management."},
    {"name": "experiments", "description": "MLOps experiment management."},
    {"name": "training-runs", "description": "MLOps training run metadata."},
    {"name": "model-artifacts", "description": "MLOps model artifact registry."},
    {"name": "sensor-readings", "description": "Sensor reading management."},
    {"name": "sensors", "description": "Sensor management."},
    {"name": "upload-jobs", "description": "Sensor data upload job management."},
    {"name": "users", "description": "Authenticated user operations."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a FastAPI application instance."""
    resolved_settings = settings if settings is not None else get_settings()
    docs_url = "/docs" if resolved_settings.environment != "production" else None
    configure_logging(
        enabled=resolved_settings.structured_logging_enabled,
        log_format=resolved_settings.log_format,
        log_level=resolved_settings.log_level,
        service=resolved_settings.log_service_name,
        environment=resolved_settings.log_environment,
        access_logging_enabled=resolved_settings.http_access_logging_enabled,
    )
    configure_tracing(
        TracingConfig(
            enabled=resolved_settings.tracing_enabled,
            service_name=resolved_settings.otel_service_name,
            service_namespace=resolved_settings.otel_service_namespace,
            environment=resolved_settings.otel_environment,
            service_version=resolved_settings.app_version,
            otlp_endpoint=resolved_settings.otel_exporter_otlp_endpoint,
            otlp_insecure=resolved_settings.otel_exporter_otlp_insecure,
            sampler=resolved_settings.otel_traces_sampler,
            sampler_arg=resolved_settings.otel_traces_sampler_arg,
        )
    )

    application = FastAPI(
        debug=False,
        title=resolved_settings.project_name,
        version=resolved_settings.app_version,
        description=(
            "Manufacturing APIs and the AI Core's authenticated synchronous and "
            "background Random Forest training, model governance, and registered "
            "prediction workflows with privacy-preserving monitoring, drift, and "
            "controlled candidate retraining."
        ),
        docs_url=docs_url,
        openapi_tags=OPENAPI_TAGS,
        redoc_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_allowed_origins),
        allow_credentials=resolved_settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            resolved_settings.request_id_header,
            resolved_settings.correlation_id_header,
        ],
        expose_headers=[
            "Retry-After",
            resolved_settings.request_id_header,
            resolved_settings.correlation_id_header,
        ],
    )
    configure_metrics(
        enabled=resolved_settings.observability_metrics_enabled,
        service=resolved_settings.observability_service_name,
        environment=resolved_settings.observability_environment,
    )
    if resolved_settings.observability_metrics_enabled:
        metrics_path = resolved_settings.observability_metrics_path
        application.add_middleware(
            PrometheusMetricsMiddleware,
            excluded_paths=frozenset(
                {
                    metrics_path,
                    "/docs",
                    "/openapi.json",
                    "/health",
                    "/redoc",
                }
            ),
        )
        application.add_route(
            metrics_path,
            metrics_response,
            methods=["GET"],
            include_in_schema=False,
            name="prometheus-metrics",
        )
    noisy_paths = frozenset(
        {
            resolved_settings.observability_metrics_path,
            "/docs",
            "/openapi.json",
            "/health",
            "/redoc",
        }
    )
    application.add_middleware(
        RequestContextLoggingMiddleware,
        request_id_header=resolved_settings.request_id_header,
        correlation_id_header=resolved_settings.correlation_id_header,
        access_logging_enabled=resolved_settings.http_access_logging_enabled,
        excluded_paths=noisy_paths,
    )
    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings
    application.include_router(api_router)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        FastAPITracingMiddleware,
        enabled=resolved_settings.tracing_enabled,
        excluded_paths=noisy_paths,
    )
    return application

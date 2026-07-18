"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.router import api_router
from app.config.settings import Settings, get_settings

OPENAPI_TAGS = [
    {
        "name": "ai",
        "description": (
            "Authenticated synchronous Random Forest training, MLflow tracking, "
            "fitted-model registration, version lookup, and registered prediction."
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

    application = FastAPI(
        title=resolved_settings.project_name,
        version=resolved_settings.app_version,
        description=(
            "Manufacturing APIs and the AI Core's authenticated synchronous "
            "Random Forest training and registered-prediction workflow."
        ),
        docs_url=docs_url,
        openapi_tags=OPENAPI_TAGS,
        redoc_url=None,
    )
    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings
    application.include_router(api_router)
    return application

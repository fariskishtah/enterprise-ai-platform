"""Top-level API router."""

from fastapi import APIRouter

from app.api.routes.ai import router as ai_router
from app.api.routes.ai_governance import router as ai_governance_router
from app.api.routes.ai_monitoring import router as ai_monitoring_router
from app.api.routes.ai_monitoring_orchestration import (
    router as ai_monitoring_orchestration_router,
)
from app.api.routes.ai_retraining import router as ai_retraining_router
from app.api.routes.auth import router as auth_router
from app.api.routes.automl import router as automl_router
from app.api.routes.companies import router as companies_router
from app.api.routes.datasets import router as datasets_router
from app.api.routes.factories import router as factories_router
from app.api.routes.feature_engineering import router as feature_engineering_router
from app.api.routes.health import router as health_router
from app.api.routes.machines import router as machines_router
from app.api.routes.mlops import (
    experiment_training_runs_router,
    experiments_router,
    model_artifacts_router,
    training_run_artifacts_router,
    training_runs_router,
)
from app.api.routes.rag import router as rag_router
from app.api.routes.sensor_data import (
    sensor_readings_nested_router,
    sensor_readings_router,
    upload_jobs_router,
)
from app.api.routes.sensors import machine_sensor_router
from app.api.routes.sensors import router as sensors_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(ai_router)
api_router.include_router(ai_governance_router)
api_router.include_router(ai_monitoring_router)
api_router.include_router(ai_monitoring_orchestration_router)
api_router.include_router(ai_retraining_router)
api_router.include_router(automl_router)
api_router.include_router(auth_router)
api_router.include_router(companies_router)
api_router.include_router(datasets_router)
api_router.include_router(feature_engineering_router)
api_router.include_router(factories_router)
api_router.include_router(health_router)
api_router.include_router(machines_router)
api_router.include_router(experiments_router)
api_router.include_router(experiment_training_runs_router)
api_router.include_router(training_runs_router)
api_router.include_router(training_run_artifacts_router)
api_router.include_router(model_artifacts_router)
api_router.include_router(rag_router)
api_router.include_router(sensors_router)
api_router.include_router(machine_sensor_router)
api_router.include_router(upload_jobs_router)
api_router.include_router(sensor_readings_router)
api_router.include_router(sensor_readings_nested_router)
api_router.include_router(users_router)

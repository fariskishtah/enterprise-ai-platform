"""Service dependencies."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.mlops import MLOpsConfigurationLoader
from app.config.settings import Settings, get_settings
from app.dependencies.database import get_db_session
from app.ml.artifacts import BaseArtifactManager, LocalArtifactManager
from app.ml.composition import create_ai_trainer_registry
from app.ml.engine import TrainingEngine
from app.ml.factory import TrainerFactory, TrainerRegistry
from app.ml.jobs import DramatiqTrainingJobQueue, TrainingJobQueue
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring import (
    MonitoredPredictionService,
    PredictionCaptureHealth,
)
from app.ml.promotion import (
    ClassificationPromotionPolicy,
    RegressionPromotionPolicy,
)
from app.ml.promotion.service import ModelPromotionService
from app.ml.registry import BaseModelRegistry, MLflowModelRegistry
from app.ml.services import (
    BaseRegisteredModelLoader,
    MLflowRegisteredModelLoader,
    PredictionService,
    TrackedTrainingService,
)
from app.ml.tracking import BaseExperimentTracker, MLflowExperimentTracker
from app.repositories.ai_governance import (
    ModelPromotionAuditRepository,
    TrainingJobRepository,
)
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.repositories.feature_engineering import FeatureEngineeringRepository
from app.repositories.manufacturing import ManufacturingRepository
from app.repositories.mlops import MLOpsRepository
from app.repositories.sensor_data import SensorDataRepository
from app.repositories.sensors import SensorRepository
from app.repositories.users import UserRepository
from app.services.authentication import AuthenticationService
from app.services.feature_engineering import FeatureEngineeringService
from app.services.manufacturing import ManufacturingService
from app.services.mlops import MLOpsService
from app.services.model_registry import (
    MLflowModelRegistry as MetadataMLflowModelRegistry,
)
from app.services.model_registry import ModelRegistry
from app.services.optuna import OptunaStudyFactory
from app.services.sensor_data import SensorDataService
from app.services.sensor_data_etl import SensorDataEtlService
from app.services.sensors import SensorService
from app.services.users import UserService
from app.utils.passwords import PasswordHasher


def get_password_hasher() -> PasswordHasher:
    """Return the password hashing adapter."""
    return PasswordHasher()


def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRepository:
    """Return the user repository."""
    return UserRepository(session)


def get_manufacturing_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ManufacturingRepository:
    """Return the manufacturing repository."""
    return ManufacturingRepository(session)


def get_sensor_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SensorRepository:
    """Return the sensor repository."""
    return SensorRepository(session)


def get_sensor_data_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SensorDataRepository:
    """Return the sensor data repository."""
    return SensorDataRepository(session)


def get_feature_engineering_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeatureEngineeringRepository:
    """Return the feature engineering repository."""
    return FeatureEngineeringRepository(session)


def get_mlops_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MLOpsRepository:
    """Return the MLOps repository."""
    return MLOpsRepository(session)


def get_model_registry(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ModelRegistry:
    """Return the configured model registry adapter."""
    return MetadataMLflowModelRegistry(
        tracking_uri=settings.mlflow_tracking_uri,
        artifact_root=settings.model_artifact_root,
    )


def get_ai_trainer_registry() -> TrainerRegistry:
    """Return a fresh registry with the supported AI Core trainers."""
    return create_ai_trainer_registry()


def get_training_job_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TrainingJobRepository:
    """Return the persistent AI training-job repository."""
    return TrainingJobRepository(session)


def get_model_promotion_audit_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModelPromotionAuditRepository:
    """Return the append-only model-promotion audit repository."""
    return ModelPromotionAuditRepository(session)


def get_training_job_queue() -> TrainingJobQueue:
    """Return the configured Redis-backed training-job queue adapter."""
    return DramatiqTrainingJobQueue()


def get_training_job_service(
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[
        TrainingJobRepository,
        Depends(get_training_job_repository),
    ],
    queue: Annotated[TrainingJobQueue, Depends(get_training_job_queue)],
) -> TrainingJobService:
    """Return the persistent job submission and lifecycle service."""
    return TrainingJobService(
        repository=repository,
        queue=queue,
        max_attempts=settings.training_job_max_attempts,
    )


def get_ai_trainer_factory(
    registry: Annotated[TrainerRegistry, Depends(get_ai_trainer_registry)],
) -> TrainerFactory:
    """Return the request-scoped AI Core trainer factory."""
    return TrainerFactory(registry)


def get_ai_artifact_manager(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BaseArtifactManager:
    """Return local persistence rooted at the configured AI artifact path."""
    return LocalArtifactManager(Path(settings.ai_artifact_root))


def get_ai_training_engine(
    trainer_factory: Annotated[TrainerFactory, Depends(get_ai_trainer_factory)],
    artifact_manager: Annotated[
        BaseArtifactManager,
        Depends(get_ai_artifact_manager),
    ],
) -> TrainingEngine:
    """Return the typed local training orchestrator."""
    return TrainingEngine(
        trainer_factory=trainer_factory,
        artifact_manager=artifact_manager,
    )


def get_ai_experiment_tracker(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BaseExperimentTracker:
    """Return the configured MLflow successful-run tracker."""
    return MLflowExperimentTracker(tracking_uri=settings.mlflow_tracking_uri)


def get_ai_model_registry(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BaseModelRegistry:
    """Return the configured fitted-model registry adapter."""
    return MLflowModelRegistry(tracking_uri=settings.mlflow_tracking_uri)


def get_ai_registered_model_loader(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BaseRegisteredModelLoader:
    """Return the configured MLflow registered-model loader."""
    return MLflowRegisteredModelLoader(tracking_uri=settings.mlflow_tracking_uri)


def get_ai_tracked_training_service(
    training_engine: Annotated[TrainingEngine, Depends(get_ai_training_engine)],
    experiment_tracker: Annotated[
        BaseExperimentTracker,
        Depends(get_ai_experiment_tracker),
    ],
    model_registry: Annotated[
        BaseModelRegistry,
        Depends(get_ai_model_registry),
    ],
) -> TrackedTrainingService:
    """Return the ordered local-training, tracking, and registry service."""
    return TrackedTrainingService(
        training_engine=training_engine,
        experiment_tracker=experiment_tracker,
        model_registry=model_registry,
    )


def get_ai_prediction_service(
    model_registry: Annotated[
        BaseModelRegistry,
        Depends(get_ai_model_registry),
    ],
    model_loader: Annotated[
        BaseRegisteredModelLoader,
        Depends(get_ai_registered_model_loader),
    ],
) -> PredictionService:
    """Return the registered-model prediction application service."""
    return PredictionService(
        model_registry=model_registry,
        model_loader=model_loader,
    )


def get_prediction_monitoring_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PredictionMonitoringRepository:
    """Return request-scoped prediction monitoring persistence."""
    return PredictionMonitoringRepository(session)


@lru_cache
def get_prediction_capture_health() -> PredictionCaptureHealth:
    """Return the restart-resetting, non-replica-aggregated instance counter."""
    return PredictionCaptureHealth()


def get_ai_monitored_prediction_service(
    prediction_service: Annotated[
        PredictionService,
        Depends(get_ai_prediction_service),
    ],
    repository: Annotated[
        PredictionMonitoringRepository,
        Depends(get_prediction_monitoring_repository),
    ],
    capture_health: Annotated[
        PredictionCaptureHealth,
        Depends(get_prediction_capture_health),
    ],
) -> MonitoredPredictionService:
    """Wrap registered prediction with noncritical privacy-safe event capture."""
    return MonitoredPredictionService(
        prediction_service=prediction_service,
        event_store=repository,
        capture_health=capture_health,
    )


def get_model_promotion_service(
    settings: Annotated[Settings, Depends(get_settings)],
    job_repository: Annotated[
        TrainingJobRepository,
        Depends(get_training_job_repository),
    ],
    audit_repository: Annotated[
        ModelPromotionAuditRepository,
        Depends(get_model_promotion_audit_repository),
    ],
    model_registry: Annotated[
        BaseModelRegistry,
        Depends(get_ai_model_registry),
    ],
) -> ModelPromotionService:
    """Return configured task policies and audited promotion orchestration."""
    return ModelPromotionService(
        job_repository=job_repository,
        audit_repository=audit_repository,
        model_registry=model_registry,
        regression_policy=RegressionPromotionPolicy(
            minimum_r2=settings.promotion_regression_min_r2,
            minimum_relative_rmse_improvement=(
                settings.promotion_regression_min_relative_rmse_improvement
            ),
        ),
        classification_policy=ClassificationPromotionPolicy(
            minimum_accuracy=settings.promotion_classification_min_accuracy,
            minimum_f1_improvement=(
                settings.promotion_classification_min_f1_improvement
            ),
        ),
    )


def get_mlops_configuration_loader(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MLOpsConfigurationLoader:
    """Return the MLOps YAML configuration loader."""
    return MLOpsConfigurationLoader(config_dir=settings.mlops_config_dir)


def get_optuna_study_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> OptunaStudyFactory:
    """Return the Optuna study factory."""
    return OptunaStudyFactory(default_storage_url=settings.optuna_storage_url)


def get_user_service(
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> UserService:
    """Return the user service."""
    return UserService(repository=repository, password_hasher=password_hasher)


def get_manufacturing_service(
    repository: Annotated[
        ManufacturingRepository,
        Depends(get_manufacturing_repository),
    ],
) -> ManufacturingService:
    """Return the manufacturing service."""
    return ManufacturingService(repository=repository)


def get_sensor_service(
    repository: Annotated[SensorRepository, Depends(get_sensor_repository)],
) -> SensorService:
    """Return the sensor service."""
    return SensorService(repository=repository)


def get_sensor_data_service(
    repository: Annotated[SensorDataRepository, Depends(get_sensor_data_repository)],
) -> SensorDataService:
    """Return the sensor data service."""
    return SensorDataService(repository=repository)


def get_sensor_data_etl_service(
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[SensorDataRepository, Depends(get_sensor_data_repository)],
) -> SensorDataEtlService:
    """Return the sensor data ETL service."""
    return SensorDataEtlService(
        repository=repository,
        chunk_size=settings.etl_chunk_size,
        float_precision=settings.etl_float_precision,
        outlier_z_score_threshold=settings.etl_outlier_z_score_threshold,
    )


def get_feature_engineering_service(
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[
        FeatureEngineeringRepository,
        Depends(get_feature_engineering_repository),
    ],
) -> FeatureEngineeringService:
    """Return the feature engineering service."""
    return FeatureEngineeringService(
        repository=repository,
        dataset_dir=settings.feature_dataset_dir,
        rolling_window_size=settings.feature_rolling_window_size,
    )


def get_mlops_service(
    repository: Annotated[MLOpsRepository, Depends(get_mlops_repository)],
    model_registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> MLOpsService:
    """Return the MLOps service."""
    return MLOpsService(repository=repository, model_registry=model_registry)


def get_authentication_service(
    settings: Annotated[Settings, Depends(get_settings)],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> AuthenticationService:
    """Return the authentication service."""
    return AuthenticationService(
        settings=settings,
        repository=repository,
        user_service=user_service,
        password_hasher=password_hasher,
    )

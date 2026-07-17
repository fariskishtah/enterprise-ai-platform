"""Service dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.mlops import MLOpsConfigurationLoader
from app.config.settings import Settings, get_settings
from app.dependencies.database import get_db_session
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
from app.services.model_registry import MLflowModelRegistry, ModelRegistry
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
    return MLflowModelRegistry(
        tracking_uri=settings.mlflow_tracking_uri,
        artifact_root=settings.model_artifact_root,
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

"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import (
    Field,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    StringConstraints,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvironmentName = Literal["local", "development", "staging", "production", "test"]
RegisteredModelPrefix = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$"),
]


class Settings(BaseSettings):
    """Typed runtime settings for the backend service."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "AI Manufacturing Platform"
    app_version: str = "0.8.0"
    database_url: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)
    secret_key: SecretStr
    environment: EnvironmentName = "local"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: PositiveInt = 15
    refresh_token_expire_days: PositiveInt = 30
    etl_chunk_size: PositiveInt = 50_000
    etl_float_precision: PositiveInt = 6
    etl_outlier_z_score_threshold: PositiveFloat = 3.0
    feature_dataset_dir: str = "../datasets/features"
    feature_rolling_window_size: PositiveInt = 5
    mlops_config_dir: str = "../ml/configs"
    mlflow_tracking_uri: str = Field(default="file:../mlruns", min_length=1)
    model_artifact_root: str = Field(
        default="../ml/model-artifacts",
        min_length=1,
    )
    ai_artifact_root: str = Field(default="../ml/ai-artifacts", min_length=1)
    ai_default_registered_model_prefix: RegisteredModelPrefix = "ai_core"
    training_queue_name: str = Field(
        default="ai-training",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    training_job_max_attempts: PositiveInt = 3
    training_job_retry_base_seconds: PositiveFloat = 5.0
    training_job_stale_after_seconds: PositiveInt = 3600
    training_job_orphaned_after_seconds: PositiveInt = 60
    optuna_storage_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()

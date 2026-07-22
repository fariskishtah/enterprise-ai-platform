"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    Field,
    FiniteFloat,
    NonNegativeFloat,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvironmentName = Literal["local", "development", "staging", "production", "test"]
LogFormat = Literal["json", "text"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
OtelTracesSampler = Literal["parentbased_traceidratio"]
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
        env_ignore_empty=True,
        extra="ignore",
    )

    project_name: str = "AI Manufacturing Platform"
    app_version: str = "0.8.0"
    database_url: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)
    secret_key: SecretStr = Field(min_length=32)
    environment: EnvironmentName = "local"
    enable_api_docs: bool = True
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = Field(
        default="ai-manufacturing-platform",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    jwt_audience: str = Field(
        default="ai-manufacturing-api",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    access_token_expire_minutes: PositiveInt = 15
    refresh_token_expire_days: PositiveInt = 30
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_requests: PositiveInt = Field(default=10, le=1000)
    auth_rate_limit_window_seconds: PositiveInt = Field(default=60, le=3600)
    mutation_rate_limit_enabled: bool = True
    mutation_rate_limit_requests: PositiveInt = Field(default=30, le=1000)
    mutation_rate_limit_window_seconds: PositiveInt = Field(default=60, le=3600)
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    cors_allow_credentials: bool = False
    structured_logging_enabled: bool = True
    log_format: LogFormat = "json"
    log_level: LogLevel = "INFO"
    http_access_logging_enabled: bool = True
    request_id_header: str = Field(
        default="X-Request-ID",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9-]*$",
    )
    correlation_id_header: str = Field(
        default="X-Correlation-ID",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9-]*$",
    )
    log_service_name: str = Field(
        default="ai-manufacturing-backend",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    log_environment: EnvironmentName = "local"
    observability_metrics_enabled: bool = True
    observability_metrics_path: str = Field(
        default="/metrics",
        min_length=2,
        max_length=128,
        pattern=r"^/[A-Za-z0-9/_-]+$",
    )
    observability_service_name: str = Field(
        default="ai-manufacturing-backend",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    observability_environment: EnvironmentName = "local"
    observability_worker_metrics_port: int = Field(default=9191, ge=1024, le=65535)
    worker_heartbeat_interval_seconds: PositiveInt = Field(default=10, le=300)
    worker_heartbeat_ttl_seconds: PositiveInt = Field(default=30, le=900)
    worker_availability_check_enabled: bool = True
    tracing_enabled: bool = True
    otel_service_name: str = Field(
        default="ai-manufacturing-backend",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    otel_worker_service_name: str = Field(
        default="ai-manufacturing-training-worker",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    otel_service_namespace: str = Field(
        default="ai-manufacturing-platform",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    otel_environment: EnvironmentName = "local"
    otel_exporter_otlp_endpoint: str = Field(
        default="http://tempo:4317",
        min_length=1,
        max_length=512,
    )
    otel_exporter_otlp_insecure: bool = True
    otel_traces_sampler: OtelTracesSampler = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0, le=1)
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
    automl_global_execution_slots: PositiveInt = Field(default=1, le=4)
    automl_trial_lease_seconds: PositiveInt = Field(default=300, le=21600)
    automl_reconciliation_scheduling_enabled: bool = True
    automl_reconciliation_interval_seconds: PositiveInt = Field(
        default=60, ge=10, le=3600
    )
    promotion_audit_pending_after_seconds: PositiveInt = 300
    promotion_regression_min_r2: FiniteFloat = Field(default=0.0, le=1)
    promotion_regression_min_relative_rmse_improvement: float = Field(
        default=0.0,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    promotion_classification_min_accuracy: float = Field(
        default=0.0,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    promotion_classification_min_f1_improvement: NonNegativeFloat = Field(
        default=0.0,
        le=1,
    )
    prediction_event_retention_days: PositiveInt = Field(default=90, le=3650)
    monitoring_min_sample_count: PositiveInt = Field(default=20, le=100_000)
    monitoring_max_window_days: PositiveInt = Field(default=30, le=365)
    monitoring_profile_bin_count: int = Field(default=10, ge=10, le=20)
    monitoring_max_events_per_window: PositiveInt = Field(
        default=10_000,
        le=100_000,
    )
    monitoring_reference_reconciliation_batch_size: PositiveInt = Field(
        default=100,
        le=1000,
    )
    prediction_event_retention_batch_size: PositiveInt = Field(
        default=1000,
        le=10_000,
    )
    monitoring_scheduling_enabled: bool = False
    monitoring_queue_name: str = Field(
        default="ai-monitoring",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    monitoring_window_hours: PositiveInt = Field(default=24, le=24 * 365)
    monitoring_evaluation_interval_seconds: PositiveInt = 3600
    monitoring_lock_timeout_seconds: PositiveInt = 1800
    monitoring_eligible_model_aliases: str = Field(
        default="champion",
        min_length=1,
        max_length=255,
    )
    monitoring_max_models_per_run: PositiveInt = Field(default=100, le=1000)
    monitoring_failure_rate_warning_threshold: float = Field(
        default=0.05, ge=0, le=1, allow_inf_nan=False
    )
    monitoring_failure_rate_critical_threshold: float = Field(
        default=0.20, gt=0, le=1, allow_inf_nan=False
    )
    monitoring_evaluation_retention_days: PositiveInt = Field(default=365, le=3650)
    monitoring_evaluation_retention_batch_size: PositiveInt = Field(
        default=500, le=10_000
    )
    monitoring_stale_alert_hours: PositiveInt = Field(default=168, le=24 * 365)
    prediction_event_retention_scheduling_enabled: bool = False
    monitoring_evaluation_retention_scheduling_enabled: bool = False
    reference_profile_reconciliation_scheduling_enabled: bool = False
    retraining_reconciliation_scheduling_enabled: bool = False
    stale_alert_reconciliation_scheduling_enabled: bool = False
    monitoring_automatic_retraining_enabled: bool = False
    monitoring_retraining_actor_user_id: UUID | None = None
    ground_truth_max_outcomes_per_summary: PositiveInt = Field(
        default=10_000, le=100_000
    )
    drift_psi_warning_threshold: float = Field(
        default=0.10,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    drift_psi_critical_threshold: float = Field(
        default=0.25,
        gt=0,
        le=2,
        allow_inf_nan=False,
    )
    drift_missing_rate_warning_threshold: float = Field(
        default=0.05,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    drift_out_of_range_warning_threshold: float = Field(
        default=0.10,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    retraining_default_cooldown_seconds: int = Field(default=86_400, ge=0)
    retraining_default_max_requests_per_day: PositiveInt = 1
    retraining_default_max_requests_per_week: PositiveInt = 3
    retraining_default_max_active_requests: PositiveInt = 1
    retraining_reconciliation_batch_size: PositiveInt = Field(
        default=100,
        le=1000,
    )
    retraining_default_minimum_drift_status: Literal["warning", "critical"] = "critical"
    retraining_allow_truncated_drift: bool = True
    optuna_storage_url: str | None = None

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_allowed_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require an explicit, credential-free HTTP(S) origin allowlist."""
        normalized_origins: list[str] = []
        for origin in value:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or origin == "*"
            ):
                raise ValueError("cors_allowed_origins contains an invalid origin.")
            normalized = f"{parsed.scheme}://{parsed.netloc}"
            if normalized not in normalized_origins:
                normalized_origins.append(normalized)
        return tuple(normalized_origins)

    @model_validator(mode="after")
    def validate_drift_threshold_order(self) -> Self:
        """Require the operational warning threshold below critical."""
        if self.environment == "production" and self.enable_api_docs:
            raise ValueError("enable_api_docs must be false in production.")
        if self.environment == "production" and any(
            urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
            for origin in self.cors_allowed_origins
        ):
            raise ValueError(
                "production cors_allowed_origins must not contain local origins."
            )
        otlp_endpoint = urlsplit(self.otel_exporter_otlp_endpoint)
        if (
            otlp_endpoint.scheme not in {"http", "https"}
            or not otlp_endpoint.hostname
            or otlp_endpoint.username is not None
            or otlp_endpoint.password is not None
            or otlp_endpoint.query
            or otlp_endpoint.fragment
        ):
            raise ValueError(
                "otel_exporter_otlp_endpoint must be a credential-free URL."
            )
        if self.drift_psi_warning_threshold >= self.drift_psi_critical_threshold:
            raise ValueError(
                "drift_psi_warning_threshold must be below the critical threshold.",
            )
        if (
            self.monitoring_failure_rate_warning_threshold
            >= self.monitoring_failure_rate_critical_threshold
        ):
            raise ValueError(
                "monitoring failure-rate warning threshold must be below critical."
            )
        if self.monitoring_window_hours > self.monitoring_max_window_days * 24:
            raise ValueError(
                "monitoring_window_hours exceeds monitoring_max_window_days."
            )
        _ = self.monitoring_aliases
        if (
            self.monitoring_automatic_retraining_enabled
            and self.monitoring_retraining_actor_user_id is None
        ):
            raise ValueError(
                "monitoring_retraining_actor_user_id is required when automatic "
                "retraining is enabled."
            )
        return self

    @property
    def monitoring_aliases(self) -> tuple[str, ...]:
        """Return normalized, bounded aliases used by scheduled evaluation."""
        aliases = tuple(
            dict.fromkeys(
                item.strip()
                for item in self.monitoring_eligible_model_aliases.split(",")
                if item.strip()
            )
        )
        if not aliases or len(aliases) > 10 or any(len(item) > 128 for item in aliases):
            raise ValueError("monitoring_eligible_model_aliases is invalid.")
        return aliases


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()

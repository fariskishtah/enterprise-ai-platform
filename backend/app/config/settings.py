"""Application settings loaded from environment variables."""

import re
from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AliasChoices,
    EmailStr,
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

from app.version import get_application_version

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
    app_version: str = Field(default_factory=get_application_version)
    database_url: str = Field(min_length=1)
    database_pool_size: PositiveInt = Field(default=10, le=30)
    database_max_overflow: int = Field(default=5, ge=0, le=30)
    database_pool_timeout_seconds: PositiveFloat = Field(default=5.0, le=60)
    database_pool_recycle_seconds: PositiveInt = Field(default=1800, le=86_400)
    redis_url: str = Field(min_length=1)
    secret_key: SecretStr = Field(min_length=32)
    environment: EnvironmentName = Field(
        default="local",
        validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT", "environment"),
    )
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
    password_reset_expire_minutes: PositiveInt = Field(default=30, le=1440)
    password_reset_resend_cooldown_seconds: PositiveInt = Field(default=60, le=3600)
    expose_local_password_reset_token: bool = False
    email_verification_required: bool = False
    email_verification_expire_hours: PositiveInt = Field(default=24, le=168)
    email_verification_resend_cooldown_seconds: PositiveInt = Field(default=60, le=3600)
    expose_local_email_verification_token: bool = False
    team_invitation_expire_hours: PositiveInt = Field(default=72, le=336)
    team_invitation_resend_cooldown_seconds: PositiveInt = Field(default=60, le=3600)
    expose_local_team_invitation_token: bool = False
    email_provider: Literal["disabled", "capture", "resend", "smtp"] = "disabled"
    resend_api_key: SecretStr | None = None
    email_from: EmailStr | None = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_FROM_ADDRESS", "EMAIL_FROM", "email_from"),
    )
    email_from_name: str = Field(
        default="FactoryMind by FK Solutions", min_length=1, max_length=100
    )
    email_reply_to: EmailStr | None = None
    support_email_to: EmailStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SUPPORT_NOTIFICATION_EMAIL", "SUPPORT_EMAIL_TO", "support_email_to"
        ),
    )
    email_max_retries: PositiveInt = Field(
        default=3,
        le=10,
        validation_alias=AliasChoices(
            "EMAIL_MAX_RETRIES", "SUPPORT_EMAIL_MAX_ATTEMPTS", "email_max_retries"
        ),
    )
    email_retry_base_seconds: PositiveFloat = Field(default=5.0, le=3600)
    email_queue_name: str = Field(
        default="transactional-email",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    email_reconciliation_scheduling_enabled: bool = True
    email_reconciliation_interval_seconds: PositiveInt = Field(
        default=60, ge=10, le=3600
    )
    email_processing_stale_seconds: PositiveInt = Field(default=300, le=86_400)
    email_reconciliation_batch_size: PositiveInt = Field(default=100, le=1000)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True
    smtp_timeout_seconds: PositiveFloat = Field(default=10.0, le=60)
    simplified_experience_enabled: bool = False
    operations_workflow_enabled: bool = False
    demo_tools_enabled: bool = False
    enable_development_seed: bool = False
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_requests: PositiveInt = Field(default=10, le=1000)
    auth_rate_limit_window_seconds: PositiveInt = Field(default=60, le=3600)
    mutation_rate_limit_enabled: bool = True
    mutation_rate_limit_requests: PositiveInt = Field(default=30, le=1000)
    mutation_rate_limit_window_seconds: PositiveInt = Field(default=60, le=3600)
    http_request_max_bytes: PositiveInt = Field(
        default=50 * 1024 * 1024,
        le=100 * 1024 * 1024,
    )
    app_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP_PUBLIC_URL", "APP_BASE_URL", "app_base_url"),
    )
    api_base_url: str | None = None
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    cors_allow_credentials: bool = True
    payment_provider: Literal["disabled", "paymob"] = "disabled"
    paymob_api_key: SecretStr | None = None
    paymob_secret_key: SecretStr | None = None
    paymob_public_key: SecretStr | None = None
    paymob_hmac_secret: SecretStr | None = None
    paymob_integration_id: PositiveInt | None = None
    paymob_expected_callback_owner: PositiveInt | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PAYMOB_EXPECTED_CALLBACK_OWNER",
            "paymob_expected_callback_owner",
            "PAYMOB_MERCHANT_ID",
            "paymob_merchant_id",
        ),
    )
    paymob_iframe_id: PositiveInt | None = None
    paymob_base_url: str = "https://accept.paymob.com"
    paymob_webhook_url: str | None = None
    payment_success_url: str | None = None
    payment_failure_url: str | None = None
    payment_currency: Literal["EGP"] = "EGP"
    payment_sandbox_mode: bool = True
    payment_http_timeout_seconds: PositiveFloat = Field(default=10.0, le=30)
    paymob_allowed_checkout_hosts: tuple[str, ...] = ("accept.paymob.com",)
    paymob_supported_source_types: tuple[str, ...] = ("card",)
    billing_commercial_model: Literal[
        "prepaid_manual_renewal", "provider_recurring_subscription"
    ] = "prepaid_manual_renewal"
    billing_checkout_expiry_minutes: PositiveInt = Field(default=30, le=1440)
    billing_return_reference_expiry_minutes: PositiveInt = Field(default=60, le=1440)
    billing_webhook_queue_name: str = Field(
        default="billing-webhooks",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    billing_webhook_max_retries: PositiveInt = Field(default=5, le=20)
    billing_webhook_retry_base_seconds: PositiveFloat = Field(default=30.0, le=3600)
    billing_webhook_queued_stale_seconds: PositiveInt = Field(default=300, le=86_400)
    billing_webhook_processing_stale_seconds: PositiveInt = Field(
        default=300, le=86_400
    )
    billing_webhook_recovery_batch_size: PositiveInt = Field(default=100, le=1000)
    billing_webhook_recovery_scheduling_enabled: bool = True
    billing_webhook_recovery_interval_seconds: PositiveInt = Field(
        default=60, ge=10, le=3600
    )
    billing_grace_period_days: PositiveInt = Field(default=7, le=90)
    billing_incomplete_expiry_hours: PositiveInt = Field(default=24, le=168)
    billing_suspension_expiry_days: PositiveInt = Field(default=30, le=365)
    billing_lifecycle_reconciliation_batch_size: PositiveInt = Field(
        default=100, le=1000
    )
    billing_lifecycle_reconciliation_scheduling_enabled: bool = True
    billing_lifecycle_reconciliation_interval_seconds: PositiveInt = Field(
        default=60, ge=10, le=3600
    )
    billing_provider_reconciliation_batch_size: PositiveInt = Field(
        default=100, le=1000
    )
    billing_provider_reconciliation_scheduling_enabled: bool = False
    billing_provider_reconciliation_interval_seconds: PositiveInt = Field(
        default=300, ge=60, le=86_400
    )
    billing_provider_reconciliation_grace_seconds: PositiveInt = Field(
        default=300, ge=60, le=86_400
    )
    billing_entitlements_enforced: bool = False
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
    dataset_storage_root: str = Field(default="../data/datasets", min_length=1)
    dataset_upload_max_bytes: PositiveInt = Field(
        default=10 * 1024 * 1024,
        le=50 * 1024 * 1024,
    )
    dataset_max_rows: PositiveInt = Field(default=10_000, le=100_000)
    dataset_max_columns: PositiveInt = Field(default=256, le=1_000)
    dataset_max_cell_characters: PositiveInt = Field(default=10_000, le=100_000)
    dataset_max_document_characters: PositiveInt = Field(
        default=1_000_000,
        le=2_000_000,
    )
    dataset_processing_stale_after_seconds: PositiveInt = Field(
        default=900,
        le=86_400,
    )
    dataset_processing_max_enqueue_attempts: PositiveInt = Field(default=3, le=10)
    dataset_reconciliation_scheduling_enabled: bool = True
    dataset_reconciliation_interval_seconds: PositiveInt = Field(
        default=60, ge=10, le=3600
    )
    dataset_queue_name: str = Field(
        default="ai-training",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    rag_queue_name: str = Field(
        default="ai-training",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    rag_queued_stale_after_seconds: PositiveInt = Field(default=300, le=86_400)
    rag_running_stale_after_seconds: PositiveInt = Field(default=900, le=86_400)
    rag_index_max_enqueue_attempts: PositiveInt = Field(default=3, le=10)
    rag_message_stale_after_seconds: PositiveInt = Field(default=300, le=86_400)
    rag_reconciliation_batch_size: PositiveInt = Field(default=100, le=1000)
    rag_reconciliation_scheduling_enabled: bool = True
    rag_reconciliation_interval_seconds: PositiveInt = Field(default=60, ge=10, le=3600)
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
    public_demo_training_max_active: PositiveInt = Field(default=1, le=5)
    public_demo_training_max_per_day: PositiveInt = Field(default=3, le=50)
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

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require exact normalized hostnames rather than wildcard patterns."""
        normalized: list[str] = []
        for host in value:
            candidate = host.strip().lower()
            if (
                not candidate
                or "*" in candidate
                or "://" in candidate
                or "/" in candidate
                or "@" in candidate
                or candidate.startswith(".")
                or candidate.endswith(".")
            ):
                raise ValueError("allowed_hosts contains an invalid exact hostname.")
            if candidate not in normalized:
                normalized.append(candidate)
        if not normalized:
            raise ValueError("allowed_hosts must contain at least one hostname.")
        return tuple(normalized)

    @field_validator("paymob_allowed_checkout_hosts")
    @classmethod
    def validate_paymob_checkout_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for host in value:
            candidate = host.strip().lower()
            if (
                not candidate
                or "*" in candidate
                or "://" in candidate
                or "/" in candidate
                or "@" in candidate
                or candidate.startswith(".")
            ):
                raise ValueError(
                    "paymob_allowed_checkout_hosts contains an invalid host."
                )
            if candidate not in normalized:
                normalized.append(candidate)
        if not normalized:
            raise ValueError("paymob_allowed_checkout_hosts must not be empty.")
        return tuple(normalized)

    @field_validator("paymob_supported_source_types")
    @classmethod
    def validate_paymob_source_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip().lower() for item in value))
        if not normalized or any(
            not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", item) for item in normalized
        ):
            raise ValueError("paymob_supported_source_types is invalid.")
        return normalized

    @field_validator("cookie_domain")
    @classmethod
    def validate_cookie_domain(cls, value: str | None) -> str | None:
        """Accept only a hostname-style cookie domain."""
        if value is None:
            return None
        normalized = value.strip().lower().lstrip(".")
        if (
            not normalized
            or len(normalized) > 253
            or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in normalized.split(".")
            )
        ):
            raise ValueError("cookie_domain must be a valid hostname.")
        return normalized

    @model_validator(mode="after")
    def validate_drift_threshold_order(self) -> Self:
        """Require the operational warning threshold below critical."""
        if self.environment == "production" and self.enable_api_docs:
            raise ValueError("enable_api_docs must be false in production.")
        if self.environment == "production" and self.demo_tools_enabled:
            raise ValueError("demo_tools_enabled must be false in production.")
        if self.environment == "production" and self.enable_development_seed:
            raise ValueError("enable_development_seed must be false in production.")
        if (
            self.environment == "production"
            and self.expose_local_email_verification_token
        ):
            raise ValueError(
                "expose_local_email_verification_token must be false in production."
            )
        if self.environment == "production" and self.expose_local_team_invitation_token:
            raise ValueError(
                "expose_local_team_invitation_token must be false in production."
            )
        if self.environment == "production" and not self.email_verification_required:
            raise ValueError("email_verification_required must be true in production.")
        if self.environment == "production" and any(
            urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
            for origin in self.cors_allowed_origins
        ):
            raise ValueError(
                "production cors_allowed_origins must not contain local origins."
            )
        if self.environment == "production":
            for name, value in (
                ("app_base_url", self.app_base_url),
                ("api_base_url", self.api_base_url),
            ):
                parsed = urlsplit(value or "")
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.fragment
                ):
                    raise ValueError(
                        f"{name} must be a credential-free HTTPS URL in production."
                    )
            if not self.cookie_secure:
                raise ValueError("cookie_secure must be true in production.")
            if any(
                host in {"localhost", "127.0.0.1", "::1"} for host in self.allowed_hosts
            ):
                raise ValueError(
                    "production allowed_hosts must not contain local hosts."
                )
            if self.email_provider not in {"resend", "smtp"}:
                raise ValueError("production email_provider must be resend or smtp.")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("cookie_secure must be true when cookie_samesite is none.")
        paymob_base = urlsplit(self.paymob_base_url)
        if (
            paymob_base.scheme not in {"http", "https"}
            or not paymob_base.hostname
            or paymob_base.username is not None
            or paymob_base.password is not None
            or paymob_base.query
            or paymob_base.fragment
        ):
            raise ValueError("paymob_base_url must be a credential-free HTTP(S) URL.")
        if self.environment == "production" and self.payment_provider != "disabled":
            raise ValueError(
                "payment_provider must remain disabled in production until a "
                "separate live-payment approval changes this release invariant."
            )
        if self.payment_provider == "paymob":
            required_paymob_values = {
                "paymob_secret_key": self.paymob_secret_key,
                "paymob_public_key": self.paymob_public_key,
                "paymob_hmac_secret": self.paymob_hmac_secret,
                "paymob_integration_id": self.paymob_integration_id,
                "paymob_expected_callback_owner": (self.paymob_expected_callback_owner),
                "paymob_webhook_url": self.paymob_webhook_url,
                "payment_success_url": self.payment_success_url,
                "payment_failure_url": self.payment_failure_url,
            }
            missing = sorted(
                name for name, value in required_paymob_values.items() if value is None
            )
            if missing:
                raise ValueError(
                    "Paymob configuration is incomplete: " + ", ".join(missing)
                )
            if (
                paymob_base.hostname or ""
            ).lower() not in self.paymob_allowed_checkout_hosts:
                raise ValueError(
                    "paymob_base_url host must be in paymob_allowed_checkout_hosts."
                )
            assert self.paymob_public_key is not None
            assert self.paymob_secret_key is not None
            for name, value in (
                ("paymob_webhook_url", self.paymob_webhook_url),
                ("payment_success_url", self.payment_success_url),
                ("payment_failure_url", self.payment_failure_url),
            ):
                parsed = urlsplit(value or "")
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.fragment
                ):
                    raise ValueError(f"{name} must be a credential-free HTTP(S) URL.")
            public_key = self.paymob_public_key.get_secret_value()
            secret_key = self.paymob_secret_key.get_secret_value()
            if self.payment_sandbox_mode and (
                public_key.startswith("pk_live_") or secret_key.startswith("sk_live_")
            ):
                raise ValueError("Live Paymob keys cannot be used in sandbox mode.")
            if not self.payment_sandbox_mode and (
                public_key.startswith("pk_test_") or secret_key.startswith("sk_test_")
            ):
                raise ValueError("Test Paymob keys cannot be used in live mode.")
        if self.billing_commercial_model == "provider_recurring_subscription":
            raise ValueError(
                "provider recurring billing is not implemented or sandbox accepted."
            )
        if self.environment == "production" and not self.billing_entitlements_enforced:
            raise ValueError(
                "billing_entitlements_enforced must be true in production."
            )
        if self.email_provider in {"capture", "resend", "smtp"} and (
            self.email_from is None
        ):
            raise ValueError(
                "email_from is required when transactional email is enabled."
            )
        if self.email_provider == "resend" and self.resend_api_key is None:
            raise ValueError(
                "resend_api_key is required when email_provider is resend."
            )
        if self.email_provider == "smtp" and not self.smtp_host:
            raise ValueError("smtp_host is required when email_provider is smtp.")
        if (self.smtp_username is None) != (self.smtp_password is None):
            raise ValueError(
                "smtp_username and smtp_password must be configured together."
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

    @property
    def support_email_max_attempts(self) -> int:
        """Compatibility name for the former support-only delivery bound."""
        return self.email_max_retries


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()

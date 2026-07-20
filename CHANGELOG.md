# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows semantic versioning.

## [Unreleased]

## [1.0.0] - 2026-07-20

### Added

- JWT authentication with refresh-token rotation and role-based access for
  administrators, engineers, and operators.
- Company, factory, machine, and sensor hierarchy APIs with validated sensor
  reading ingestion and bounded CSV ETL.
- Synchronous and Redis-backed Random Forest regression and classification
  training, deterministic small-job support, and dedicated worker execution.
- MLflow tracking, immutable model registration and version lookup, controlled
  candidate/challenger/champion aliases, and audited promotion decisions.
- Exact-version registered prediction with privacy-preserving prediction-event
  capture, operational summaries, data-quality reports, reference profiles, and
  bounded drift analysis.
- Policy-controlled retraining evaluation with persisted cooldowns, quotas,
  source-job lineage, audit history, and candidate comparison. Retraining does
  not automatically promote a model.
- Local Docker Compose observability with Prometheus, Grafana, Alertmanager,
  Loki, Alloy, Tempo, bounded labels, structured logs, tracing, SLOs, alerts,
  dashboards, and operator runbooks.
- Single-VM production Compose assets, migration/deploy/verify/rollback scripts,
  backup and restore-verification guidance, and optional observability profile.
- One focused end-to-end workflow test covering authentication through monitored
  prediction, plus a repeatable idempotent local demo seed workflow.
- Pinned local Alertmanager with persistent state, localhost-only access,
  severity routing, null receivers, grouping, and duplicate inhibition.
- Five 30-day SLOs with stable multi-window recording rules, error-budget
  dashboards, fast/medium/slow/ticket burn alerts, and bounded application,
  dependency, resource, and observability alerts.
- Alerting and SLO documentation plus operator runbooks for API, worker,
  training, monitoring/retraining, database/cache, telemetry services, resource
  pressure, and burn-rate response.
- A bounded terminal-outcome Dramatiq metric supporting an exact background-job
  success denominator without exposing job, tenant, model, or payload identity.
- Explicit bounded OpenTelemetry dependencies, typed trace settings, idempotent
  backend/worker providers, OTLP/gRPC export, and active-span JSON `trace_id`
  correlation.
- Normalized FastAPI server spans, parameter-safe SQLAlchemy and Redis client
  spans, bounded AI domain spans, and explicit W3C Dramatiq propagation across
  producers, consumers, and retries.
- Pinned local Grafana Tempo with persistent filesystem storage, fixed Grafana
  datasource UID, bidirectional Loki links, Prometheus links, and two
  provisioned tracing dashboards.
- Dependency-free structured JSON/text logging with a stable safe field schema,
  redaction, sanitized exception stacks, configurable levels, and failure
  isolation.
- Validated request and correlation IDs on API responses, normalized HTTP
  completion logs, and Dramatiq correlation propagation with lifecycle logs for
  every background actor.
- Pinned local Loki and Alloy services with seven-day filesystem retention,
  bounded Docker log labels, persistent positions, and localhost-only ports.
- Provisioned Grafana Loki datasource plus Logs Overview and Request Correlation
  dashboards.
- Configurable FastAPI and Dramatiq Prometheus metrics with normalized HTTP route
  labels and bounded AI-operation dimensions.
- A local Prometheus, Grafana, PostgreSQL exporter, Redis exporter, and cAdvisor
  stack with provisioned Platform Overview, Backend API, and AI Operations
  dashboards.
- Persisted exact-version monitoring evaluations with bounded reports,
  deterministic status, database idempotency, and authenticated history APIs.
- Deduplicated internal monitoring alerts with acknowledgement, automatic
  resolution, and stale reconciliation.
- Explicitly enabled Dramatiq actors for monitoring, retention, and existing
  reconciliation operations with database-backed execution locks.
- Monitoring-evaluation lineage for controlled retraining requests and audits.
- Mature prediction outcomes plus bounded regression and binary-classification
  performance summaries without weakening summary-only prediction telemetry.

## [0.8.0] - 2026-07-17

### Added

- MLOps experiment management foundation with Experiment, TrainingRun, and ModelArtifact entities.
- Alembic migration, repository layer, service layer, REST APIs, RBAC, and dependency injection for MLOps metadata.
- MLflow registry adapter for metadata synchronization, YAML configuration loading, and Optuna study setup without model training.
- Repository, API, configuration, MLflow integration, and migration tests.

### Changed

- Backend application version updated to `0.8.0`.

## [0.7.0] - 2026-07-17

### Added

- Feature engineering pipeline using Polars to generate time, rolling-window, lag, statistical, and delta features from validated sensor readings.
- Versioned Parquet dataset exports through the backend API.
- Unit, pipeline, API, feature validation, and performance smoke tests for feature engineering.

### Changed

- Backend application version updated to `0.7.0`.

## [0.6.0] - 2026-07-17

### Added

- CSV ETL pipeline for sensor readings with Polars streaming, Pandera schema validation, cleaning, UTC normalization, statistical outlier detection, bulk insert, upload job finalization, and backend tests.

### Changed

- Backend application version updated to `0.6.0`.

## [0.5.0] - 2026-07-17

### Added

- Sensor data platform with upload jobs, one-row-per-reading storage, validation, RBAC, Alembic migration, and backend tests.

### Changed

- Backend application version updated to `0.5.0`.

## [0.4.0] - 2026-07-17

### Added

- Sensor management for machines, including ORM model, Alembic migration, CRUD APIs, RBAC, validation, and backend tests.

### Changed

- Backend application version updated to `0.4.0`.

## [0.3.0] - 2026-07-17

### Added

- Manufacturing domain models for companies, factories, and machines.
- Alembic migration for `companies`, `factories`, and `machines`.
- UUID primary keys, timestamps, soft delete support, indexes, and relationships for manufacturing tables.
- CRUD APIs for companies, factories, and machines.
- Pagination, filtering, searching, and sorting for manufacturing list endpoints.
- RBAC enforcement for manufacturing APIs:
  - Admin: full access.
  - Engineer: create, update, and read.
  - Operator: read only.
- Repository and service layers for manufacturing domain behavior.
- API, repository, service, RBAC, and validation tests for the manufacturing domain.
- Engineering documentation for architecture, API, database, security, and development workflows.

### Changed

- Backend application version updated to `0.3.0`.
- Documentation updated to include the manufacturing domain and current database schema.

## [0.2.0] - 2026-07-17

### Added

- FastAPI authentication routes for registration, login, refresh-token rotation, logout, and current-user retrieval.
- SQLAlchemy user and refresh-token ORM models with UUID primary keys.
- Alembic migration for `users` and `refresh_tokens`.
- JWT access tokens and refresh tokens.
- Refresh-token persistence using SHA-256 token digests.
- Refresh-token rotation and logout revocation.
- pwdlib Argon2 password hashing.
- Role-based access control for `admin`, `engineer`, and `operator`.
- FastAPI dependencies for database sessions, repositories, services, current user resolution, and role enforcement.
- Backend unit and API tests for authentication, token behavior, RBAC, validation, and OpenAPI documentation.

### Changed

- Backend application version updated to `0.2.0`.
- Backend documentation updated for authentication and user management.

### Security

- Passwords are never stored in plaintext.
- Refresh tokens are persisted as irreversible SHA-256 digests.
- Bearer access-token validation loads the current active user before returning protected data.

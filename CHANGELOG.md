# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows semantic versioning.

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

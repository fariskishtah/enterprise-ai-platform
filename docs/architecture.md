# Architecture

This document describes the AI Manufacturing Platform as of version `0.3.0`.

## Overall Architecture

The platform is a monorepo with a FastAPI backend, Vite React frontend, PostgreSQL database, Redis cache boundary, Docker runtime assets, and engineering documentation. The backend currently implements authentication, user management, RBAC, and the core manufacturing domain: companies, factories, and machines.

## System Diagram

```mermaid
flowchart LR
    Browser[Browser] --> Frontend[Vite React Frontend]
    Frontend --> Backend[FastAPI Backend]
    Backend --> Postgres[(PostgreSQL)]
    Backend --> Redis[(Redis)]
    Backend --> Alembic[Alembic Migrations]
    Backend --> Docs[OpenAPI /docs]
```

## Monorepo Architecture

```text
ai-manufacturing-platform/
  backend/          FastAPI service, Alembic migrations, backend tests
  frontend/         Vite React TypeScript application
  docker/           Backend and frontend Dockerfiles
  docs/             Engineering documentation
  infrastructure/   Future infrastructure-as-code boundary
  ml/               Future ML boundary
  datasets/         Future dataset boundary
  scripts/          Developer automation
```

The top-level directories intentionally separate product runtime code from future ML, dataset, and infrastructure work. Sprint 3 does not implement ML, sensor ingestion, prediction, RAG, or computer vision.

## Backend Clean Architecture

The backend separates transport, validation, use cases, persistence, and infrastructure:

- `app/api`: FastAPI routes.
- `app/schemas`: Pydantic v2 request and response models.
- `app/services`: application use cases for auth, users, and manufacturing.
- `app/repositories`: SQLAlchemy persistence adapters.
- `app/models`: SQLAlchemy ORM models.
- `app/dependencies`: FastAPI dependency injection.
- `app/utils`: JWT, password hashing, and security helpers.

```mermaid
flowchart TB
    Routes[API Routes] --> Schemas[Pydantic Schemas]
    Routes --> Dependencies[FastAPI Dependencies]
    Dependencies --> Services[Service Layer]
    Services --> Repositories[Repositories]
    Repositories --> Models[SQLAlchemy Models]
    Repositories --> Database[(PostgreSQL)]
    Services --> Utils[Security Utilities]
```

## Frontend Architecture

The frontend is a TypeScript React app built with Vite. React Router owns routing, TailwindCSS owns styling, and the current page is the Dashboard at `/`. The frontend has not yet integrated the Sprint 3 backend APIs.

## Authentication Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant Auth as AuthenticationService
    participant Repo as UserRepository
    participant DB as PostgreSQL

    Client->>API: POST /auth/login
    API->>Auth: login(email, password)
    Auth->>Repo: get_by_email(email)
    Repo->>DB: SELECT users
    DB-->>Repo: user
    Auth->>Auth: verify Argon2 password hash
    Auth->>Auth: create access JWT and refresh JWT
    Auth->>Repo: persist refresh token digest
    Repo->>DB: INSERT refresh_tokens
    Auth-->>API: token pair
    API-->>Client: 200 TokenResponse
```

Access tokens are bearer JWTs. Refresh tokens are JWTs whose SHA-256 digests are persisted so refresh tokens can be rotated and revoked.

## Dependency Injection

FastAPI dependency injection composes the runtime graph:

- `get_settings` loads typed Pydantic settings.
- `get_db_session` yields an async SQLAlchemy session.
- `get_user_repository` and `get_manufacturing_repository` inject persistence.
- `get_user_service`, `get_authentication_service`, and `get_manufacturing_service` inject use cases.
- `get_current_user` validates bearer access tokens and loads the active user.
- `require_roles` enforces RBAC.

## Request Flow

```mermaid
flowchart LR
    Request[HTTP Request] --> Router[FastAPI Router]
    Router --> Validation[Pydantic Validation]
    Validation --> DI[Dependency Resolution]
    DI --> RBAC[Authentication and RBAC]
    RBAC --> Service[Service Layer]
    Service --> Repo[Repository]
    Repo --> DB[(Database)]
    DB --> Repo
    Repo --> Service
    Service --> ResponseModel[Pydantic Response Model]
    ResponseModel --> Client[HTTP Response]
```

## Database Architecture

The backend uses SQLAlchemy 2.0 ORM models and Alembic migrations. Current tables:

- `users`
- `refresh_tokens`
- `companies`
- `factories`
- `machines`

Manufacturing entities use UUID primary keys, `created_at`, `updated_at`, and nullable `deleted_at` for soft delete support.

```mermaid
erDiagram
    USERS ||--o{ REFRESH_TOKENS : owns
    COMPANIES ||--o{ FACTORIES : owns
    FACTORIES ||--o{ MACHINES : owns

    USERS {
        uuid id PK
        string email UK
        string hashed_password
        string role
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    REFRESH_TOKENS {
        uuid id PK
        uuid user_id FK
        uuid jti UK
        string token_hash UK
        datetime expires_at
        datetime revoked_at
        datetime created_at
    }
    COMPANIES {
        uuid id PK
        string name
        string normalized_name UK
        text description
        datetime created_at
        datetime updated_at
        datetime deleted_at
    }
    FACTORIES {
        uuid id PK
        uuid company_id FK
        string name
        string location
        text description
        datetime created_at
        datetime updated_at
        datetime deleted_at
    }
    MACHINES {
        uuid id PK
        uuid factory_id FK
        string name
        string serial_number
        string manufacturer
        string model
        datetime created_at
        datetime updated_at
        datetime deleted_at
    }
```

## Docker Architecture

Docker Compose defines:

- `backend`: FastAPI served by Uvicorn.
- `frontend`: Vite development server.
- `postgres`: PostgreSQL 16.
- `redis`: Redis 7 cache boundary.

Backend configuration is injected through environment variables documented in `.env.example`.

## Component Diagram

```mermaid
flowchart TB
    subgraph Backend
        API[Routes]
        DI[Dependencies]
        Auth[AuthenticationService]
        Users[UserService]
        Manufacturing[ManufacturingService]
        UserRepo[UserRepository]
        ManufacturingRepo[ManufacturingRepository]
        JWT[JWT Utilities]
        Passwords[Password Utilities]
    end
    API --> DI
    DI --> Auth
    DI --> Users
    DI --> Manufacturing
    Auth --> Users
    Auth --> UserRepo
    Users --> UserRepo
    Manufacturing --> ManufacturingRepo
    Auth --> JWT
    Auth --> Passwords
    UserRepo --> DB[(PostgreSQL)]
    ManufacturingRepo --> DB
```

## Sequence Diagram

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant CurrentUser as get_current_user
    participant RBAC as require_roles
    participant Service as ManufacturingService
    participant Repo as ManufacturingRepository
    participant DB

    Client->>API: POST /companies with Bearer token
    API->>CurrentUser: decode token and load user
    CurrentUser->>DB: SELECT users
    DB-->>CurrentUser: active admin or engineer
    API->>RBAC: require admin or engineer
    API->>Service: create_company(payload)
    Service->>Repo: check normalized name
    Repo->>DB: SELECT companies
    Service->>Repo: create company
    Repo->>DB: INSERT companies
    Service-->>API: company
    API-->>Client: 201 CompanyResponse
```

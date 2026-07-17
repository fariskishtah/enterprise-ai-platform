# API Documentation

This document describes every endpoint implemented in version `0.3.0`.

## Common Headers

JSON request endpoints:

```http
Content-Type: application/json
```

Authenticated endpoints:

```http
Authorization: Bearer <access_token>
```

## Common Pagination Response

List endpoints return:

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

## GET /health

Purpose: report service liveness.

Authentication: none.

Responses:

- `200 OK`

cURL:

```bash
curl http://localhost:8000/health
```

## POST /auth/register

Purpose: register a new `operator` user.

Authentication: none.

Body:

```json
{
  "email": "operator@example.com",
  "password": "ValidPassword1!"
}
```

Validation:

- Email must be valid and unique after lowercase normalization.
- Password must be 12 to 128 characters.
- Password must include lowercase, uppercase, number, and special characters.
- Password must not contain whitespace.

Responses:

- `201 Created`
- `409 Conflict`
- `422 Unprocessable Content`

cURL:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@example.com","password":"ValidPassword1!"}'
```

## POST /auth/login

Purpose: authenticate a user and issue an access-token and refresh-token pair.

Authentication: none.

Body:

```json
{
  "email": "operator@example.com",
  "password": "ValidPassword1!"
}
```

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `422 Unprocessable Content`

Example response:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 900
}
```

cURL:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@example.com","password":"ValidPassword1!"}'
```

## POST /auth/refresh

Purpose: rotate a refresh token and issue a new token pair.

Authentication: refresh token in request body.

Body:

```json
{
  "refresh_token": "<refresh_jwt>"
}
```

Validation:

- Refresh token must be a valid `typ=refresh` JWT.
- Refresh token digest must exist in the database.
- Refresh token must not be expired or revoked.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `422 Unprocessable Content`

cURL:

```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_jwt>"}'
```

## POST /auth/logout

Purpose: revoke a refresh token.

Authentication: refresh token in request body.

Body:

```json
{
  "refresh_token": "<refresh_jwt>"
}
```

Responses:

- `204 No Content`
- `401 Unauthorized`
- `422 Unprocessable Content`

cURL:

```bash
curl -X POST http://localhost:8000/auth/logout \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_jwt>"}'
```

## GET /users/me

Purpose: return the authenticated active user.

Authentication: bearer access token.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`

cURL:

```bash
curl http://localhost:8000/users/me \
  -H "Authorization: Bearer <access_token>"
```

## Company Endpoints

Company response shape:

```json
{
  "id": "f2a27f3b-03bd-4a9c-8ec5-0fe2d1c9fd8c",
  "name": "Acme Manufacturing",
  "description": "Industrial operations group",
  "created_at": "2026-07-17T13:00:00Z",
  "updated_at": "2026-07-17T13:00:00Z"
}
```

### GET /companies

Purpose: list active companies.

Authentication: `admin`, `engineer`, or `operator`.

Query parameters:

- `limit`: integer, `1..100`, default `20`.
- `offset`: integer, minimum `0`, default `0`.
- `search`: optional string, searches name and description.
- `sort_by`: `name`, `created_at`, or `updated_at`, default `created_at`.
- `sort_order`: `asc` or `desc`, default `asc`.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `422 Unprocessable Content`

cURL:

```bash
curl "http://localhost:8000/companies?limit=20&offset=0&sort_by=name" \
  -H "Authorization: Bearer <access_token>"
```

### POST /companies

Purpose: create a company.

Authentication: `admin` or `engineer`.

Body:

```json
{
  "name": "Acme Manufacturing",
  "description": "Industrial operations group"
}
```

Validation:

- `name` is required, trimmed, `1..255` characters.
- `description` is optional, trimmed, `1..1000` characters when provided.
- Company name must be unique after normalization.

Responses:

- `201 Created`
- `401 Unauthorized`
- `403 Forbidden`
- `409 Conflict`
- `422 Unprocessable Content`

cURL:

```bash
curl -X POST http://localhost:8000/companies \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Manufacturing","description":"Industrial operations group"}'
```

### GET /companies/{company_id}

Purpose: get an active company by ID.

Authentication: `admin`, `engineer`, or `operator`.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl http://localhost:8000/companies/<company_id> \
  -H "Authorization: Bearer <access_token>"
```

### PATCH /companies/{company_id}

Purpose: update a company.

Authentication: `admin` or `engineer`.

Body:

```json
{
  "name": "Acme Robotics",
  "description": "Updated operations group"
}
```

Validation:

- At least one field is required.
- `name` cannot be explicit `null`.
- Updated name must remain unique after normalization.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `409 Conflict`
- `422 Unprocessable Content`

cURL:

```bash
curl -X PATCH http://localhost:8000/companies/<company_id> \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Robotics"}'
```

### DELETE /companies/{company_id}

Purpose: soft delete a company and its factories and machines.

Authentication: `admin`.

Responses:

- `204 No Content`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl -X DELETE http://localhost:8000/companies/<company_id> \
  -H "Authorization: Bearer <access_token>"
```

## Factory Endpoints

Factory response shape:

```json
{
  "id": "ac6b8159-2e80-4f34-9782-2f5b20d6dc1d",
  "company_id": "f2a27f3b-03bd-4a9c-8ec5-0fe2d1c9fd8c",
  "name": "Detroit Assembly",
  "location": "Detroit",
  "description": "Assembly operations",
  "created_at": "2026-07-17T13:00:00Z",
  "updated_at": "2026-07-17T13:00:00Z"
}
```

### GET /factories

Purpose: list active factories.

Authentication: `admin`, `engineer`, or `operator`.

Query parameters:

- `limit`: integer, `1..100`, default `20`.
- `offset`: integer, minimum `0`, default `0`.
- `search`: optional string, searches name, location, and description.
- `company_id`: optional UUID filter.
- `sort_by`: `name`, `location`, `created_at`, or `updated_at`, default `created_at`.
- `sort_order`: `asc` or `desc`, default `asc`.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `422 Unprocessable Content`

cURL:

```bash
curl "http://localhost:8000/factories?company_id=<company_id>&sort_by=name" \
  -H "Authorization: Bearer <access_token>"
```

### POST /factories

Purpose: create a factory for an existing active company.

Authentication: `admin` or `engineer`.

Body:

```json
{
  "company_id": "f2a27f3b-03bd-4a9c-8ec5-0fe2d1c9fd8c",
  "name": "Detroit Assembly",
  "location": "Detroit",
  "description": "Assembly operations"
}
```

Validation:

- `company_id` must reference an existing active company.
- `name` is required, trimmed, `1..255` characters.
- `location` is optional, trimmed, `1..255` characters when provided.
- `description` is optional, trimmed, `1..1000` characters when provided.

Responses:

- `201 Created`
- `401 Unauthorized`
- `403 Forbidden`
- `422 Unprocessable Content`

cURL:

```bash
curl -X POST http://localhost:8000/factories \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"company_id":"<company_id>","name":"Detroit Assembly","location":"Detroit"}'
```

### GET /factories/{factory_id}

Purpose: get an active factory by ID.

Authentication: `admin`, `engineer`, or `operator`.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl http://localhost:8000/factories/<factory_id> \
  -H "Authorization: Bearer <access_token>"
```

### PATCH /factories/{factory_id}

Purpose: update a factory.

Authentication: `admin` or `engineer`.

Body:

```json
{
  "name": "Detroit Assembly North",
  "location": "Detroit",
  "description": "Updated assembly operations"
}
```

Validation:

- At least one field is required.
- `company_id` and `name` cannot be explicit `null`.
- Updated `company_id` must reference an existing active company.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl -X PATCH http://localhost:8000/factories/<factory_id> \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Detroit Assembly North"}'
```

### DELETE /factories/{factory_id}

Purpose: soft delete a factory and its machines.

Authentication: `admin`.

Responses:

- `204 No Content`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl -X DELETE http://localhost:8000/factories/<factory_id> \
  -H "Authorization: Bearer <access_token>"
```

## Machine Endpoints

Machine response shape:

```json
{
  "id": "2bfa949e-3679-475e-88ce-49bb86cf68cb",
  "factory_id": "ac6b8159-2e80-4f34-9782-2f5b20d6dc1d",
  "name": "CNC Mill 01",
  "serial_number": "CNC-001",
  "manufacturer": "Okuma",
  "model": "MB-5000H",
  "created_at": "2026-07-17T13:00:00Z",
  "updated_at": "2026-07-17T13:00:00Z"
}
```

### GET /machines

Purpose: list active machines.

Authentication: `admin`, `engineer`, or `operator`.

Query parameters:

- `limit`: integer, `1..100`, default `20`.
- `offset`: integer, minimum `0`, default `0`.
- `search`: optional string, searches name, serial number, manufacturer, and model.
- `factory_id`: optional UUID filter.
- `company_id`: optional UUID filter through the owning factory.
- `sort_by`: `name`, `serial_number`, `created_at`, or `updated_at`, default `created_at`.
- `sort_order`: `asc` or `desc`, default `asc`.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `422 Unprocessable Content`

cURL:

```bash
curl "http://localhost:8000/machines?factory_id=<factory_id>&search=cnc" \
  -H "Authorization: Bearer <access_token>"
```

### POST /machines

Purpose: create a machine for an existing active factory.

Authentication: `admin` or `engineer`.

Body:

```json
{
  "factory_id": "ac6b8159-2e80-4f34-9782-2f5b20d6dc1d",
  "name": "CNC Mill 01",
  "serial_number": "CNC-001",
  "manufacturer": "Okuma",
  "model": "MB-5000H"
}
```

Validation:

- `factory_id` must reference an existing active factory.
- `name` is required, trimmed, `1..255` characters.
- Optional text fields are trimmed and limited to `1..255` characters when provided.

Responses:

- `201 Created`
- `401 Unauthorized`
- `403 Forbidden`
- `422 Unprocessable Content`

cURL:

```bash
curl -X POST http://localhost:8000/machines \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"factory_id":"<factory_id>","name":"CNC Mill 01","serial_number":"CNC-001"}'
```

### GET /machines/{machine_id}

Purpose: get an active machine by ID.

Authentication: `admin`, `engineer`, or `operator`.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl http://localhost:8000/machines/<machine_id> \
  -H "Authorization: Bearer <access_token>"
```

### PATCH /machines/{machine_id}

Purpose: update a machine.

Authentication: `admin` or `engineer`.

Body:

```json
{
  "name": "CNC Mill 02",
  "serial_number": "CNC-002",
  "manufacturer": "Okuma",
  "model": "MB-5000H"
}
```

Validation:

- At least one field is required.
- `factory_id` and `name` cannot be explicit `null`.
- Updated `factory_id` must reference an existing active factory.

Responses:

- `200 OK`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl -X PATCH http://localhost:8000/machines/<machine_id> \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"CNC Mill 02"}'
```

### DELETE /machines/{machine_id}

Purpose: soft delete a machine.

Authentication: `admin`.

Responses:

- `204 No Content`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Content`

cURL:

```bash
curl -X DELETE http://localhost:8000/machines/<machine_id> \
  -H "Authorization: Bearer <access_token>"
```

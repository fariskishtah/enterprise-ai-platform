# Repository audit

## Audit record

- Audit date: 2026-07-23
- Audited commit: `4d3ec92306e2362cc3532b945881075445bcf41c`
- Branch: `main`
- Starting working tree: clean
- Tracked files at audit start: 612
- Intended release: controlled pilot `0.9.0`

This record describes the repository at the start of the release-readiness work.
Implementation, migrations, routes, tests, and runtime configuration were treated
as authoritative when documentation disagreed.

## Version declarations discovered

| Location | Value at audit start | Finding |
| --- | --- | --- |
| Backend package metadata | `0.8.0` | Stale |
| Backend runtime/OpenAPI default | `0.8.0` | Stale |
| Frontend package and lock metadata | `0.1.0` | Stale |
| Changelog/release documents | `1.0.0` | Overstated for a controlled pilot |
| Database and API guides | `0.3.0` | Obsolete |
| Canonical version source | None | Release blocker |

The controlled-pilot reconciliation establishes root `VERSION` as the canonical
source and synchronizes package metadata to `0.9.0`.

## Implemented capabilities

- JWT authentication, refresh-token rotation, three roles, and backend RBAC.
- Company, factory, machine, sensor, reading, and bounded CSV-upload workflows.
- Owner-scoped dataset registry with immutable tabular and document versions.
- Synchronous compatibility training plus persisted Dramatiq training jobs.
- Explicit sklearn algorithm plugins, bounded AutoML studies/trials, MLflow
  tracking, version registration, and governed aliases.
- Exact-version prediction, summary-only event history, evaluation reference
  profiles, operational metrics, data-quality reports, and drift analysis.
- Persisted monitoring evaluations, internal alerts, prediction outcomes, and
  policy-controlled retraining that creates candidates without auto-promotion.
- Knowledge bases over authorized immutable document versions, asynchronous
  indexing, PostgreSQL pgvector storage/ranking, cancellation, reconciliation,
  grounded outcomes, citations, and owner-scoped conversations.
- React application routes for the supported manufacturing, data, ML, monitoring,
  dataset, knowledge, and chat workflows.
- Docker Compose local, staging, and single-host production topologies; optional
  HTTPS; paired PostgreSQL/dataset backup and isolated restore verification;
  smoke, rollback, demo, and staging helpers.
- Prometheus, Grafana, Alertmanager, Loki, Alloy, Tempo, exporters, structured
  logging, OpenTelemetry, dashboards, rules, and runbooks.

## Incomplete or limited capabilities

- User administration is not implemented beyond self-registration as operator
  and the authenticated current-user endpoint.
- Password recovery/change, MFA, SSO/SAML/OIDC, session/device management,
  SCIM, tenant provisioning, and billing/entitlements are absent.
- Audit APIs cover selected promotion and retraining records, not every
  authentication, data, and administrative event.
- Dataset storage, MLflow, model artifacts, and telemetry use local named
  volumes; there is no HA topology or application-managed off-host storage.
- RAG accepts bounded CSV or plain UTF-8 text. It has no PDF/DOCX/OCR/connectors.
- The local hashing embedding and extractive answer providers are deterministic
  pilot implementations, not semantic embedding or general LLM services.
- External paging, managed secrets, compliance certification, and production
  capacity evidence are not provided.

## Release blockers found

1. No repository software licence or documented redistribution grant.
2. No canonical version and conflicting `0.1.0`, `0.3.0`, `0.8.0`, and `1.0.0`
   declarations.
3. README, architecture, API, database, demo, and RAG documentation contradicted
   current source.
4. Backend dependencies were range-based and CI/Docker did not consume a hashed
   lockfile.
5. CI lacked dedicated secret, SAST, container, SBOM, and licence-inventory jobs.
6. Two development-only Black advisories were waived without a repository
   exception register.
7. The `/users` navigation item implied an unavailable administration product.
8. The production frontend emitted a JavaScript chunk warning and shipped a
   6.2 MiB login image.
9. Release validation was spread across several scripts/workflows with no
   top-level fast/full command.
10. Current release evidence did not establish a Python 3.12 full-suite result.

## Validation limitations at audit time

- The first audit shell exposed Python 3.14 as `python3`; the supported
  `/opt/homebrew/bin/python3.12` executable was subsequently located.
- Production and staging runtime checks require Docker daemon availability and
  build/network time.
- Real-backend browser tests require the isolated staging runtime and disposable
  credentials.
- Legal ownership, licence selection, customer terms, and asset provenance
  require owner/legal decisions and cannot be established from source code.

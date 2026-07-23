# Controlled pilot supported scope

## Release posture

Version `0.9.0` is a controlled-pilot release. It is suitable for reviewed,
bounded use in an isolated customer or staging environment after the required
security, legal, deployment, backup, and acceptance gates are completed. It is
not a claim of high availability, compliance certification, or unattended
enterprise production readiness.

## Supported capabilities

### Access and manufacturing data

- Email/password authentication, rotating refresh tokens, and admin, engineer,
  and operator role enforcement.
- Company, factory, machine, and sensor hierarchy.
- Manual sensor readings and bounded CSV validation/import with upload-job
  summaries.

### Data and AI lifecycle

- Owner-scoped dataset registry and immutable tabular/document versions.
- Bounded CSV and plain-text ingestion, inferred schema/lineage, asynchronous
  processing, cancellation where exposed, and stale-work reconciliation.
- Explicit sklearn training plugins, background jobs, deterministic evaluation,
  MLflow tracking, registered versions, and candidate/challenger/champion
  governance.
- Bounded AutoML studies and trials using allowlisted search spaces, durable
  execution slots, cancellation, reconciliation, and leaderboard results.
- Exact registered-version prediction for supported task/model contracts.
- Privacy-conscious prediction events, operational summaries, data-quality
  reports, reference profiles, feature/prediction drift, persisted evaluations,
  alerts, and observed outcomes.
- Controlled retraining policies, cooldowns, quotas, source lineage, decision
  audits, candidate comparison, and candidate-only output. Production aliases
  are never automatically promoted.

### Document knowledge and grounded chat

- Owner-scoped document datasets and knowledge bases.
- Attachment of authorized immutable ready dataset versions.
- Asynchronous, cancellable RAG indexing through the worker.
- PostgreSQL pgvector storage with bounded, authorized cosine-similarity ranking.
- Persisted owner-scoped conversations and message states.
- Grounded or explicit insufficient-evidence outcomes with citations.
- Idempotent submission and stale index/message reconciliation.

### Operations

- Local, isolated staging, and single-host production Docker Compose layouts.
- Nginx reverse proxy, optional HTTPS configuration, non-root/read-only
  application containers, health/readiness/operational probes, and worker
  heartbeat.
- Structured logs, metrics, traces, dashboards, alerts, SLO examples, and
  runbooks using Prometheus, Grafana, Alertmanager, Loki, Alloy, and Tempo.
- Paired PostgreSQL/dataset backups, checksums, isolated restore verification,
  deployment verification, read-only smoke tests, and application rollback.

## Implemented limitations

- Public registration creates operators. There is no administration interface
  for invitations, role changes, deactivation, or account recovery.
- Audit visibility is partial: promotion and retraining domain records are
  queryable; other security/operational events remain in structured logs.
- RAG uses deterministic lexical hash embeddings and bounded extractive answers.
  It is not a semantic transformer or general-purpose LLM assistant.
- Dataset/RAG inputs are bounded CSV and one plain UTF-8 text object per version.
- Storage and ML/telemetry state are local volumes in the supplied topology.
- The checked-in Alertmanager configuration has no customer paging destination.
- Deployment is a single Docker host with no automatic failover.

## Explicitly Out of Scope for This Release

- Full user administration or account lifecycle automation.
- Password reset/change, MFA, SSO, SAML, OIDC, SCIM, device/session management,
  and enterprise identity-provider integration.
- Multi-tenant organization provisioning, tenant billing, metering,
  entitlements, subscriptions, or customer self-service administration.
- A complete immutable audit-event API, SIEM export, legal hold, or compliance
  certification.
- High availability, horizontal orchestration, automatic failover, zero-downtime
  schema migration, or multi-region disaster recovery.
- Application-managed off-host object storage, encrypted backup custody, or
  managed secret storage.
- Premium semantic embeddings, external LLM generation, agents, tools, browsing,
  arbitrary URLs, or automated actions from chat.
- PDF, DOCX, OCR, images, archives, multi-file bundles, industrial connectors,
  MQTT, Kafka, or edge-device management.
- Computer vision, deep-learning training, arbitrary user-supplied code, or an
  unrestricted model marketplace.
- Automatic production model promotion or prediction-path online retraining.
- Contractual SLA, production-scale capacity certification, external paging,
  24/7 support, or regulatory/export classification.

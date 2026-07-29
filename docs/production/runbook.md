# Production operations runbook

This is the first-response index for the production platform. Replace every
`<deployment-owned value>` before launch. Never paste credentials, callback
payloads, access tokens, customer content, or raw database exports into tickets
or chat. Use correlation IDs and provider reference IDs for investigation.

## First five minutes

1. Declare an incident and assign incident commander, operations lead, and
   communications lead according to `incident-response.md`.
2. Record UTC time, release/image digests, active alerts, and the last known good
   state. Preserve bounded logs before restarting anything.
3. Check `/api/health`, `/api/ready`, Grafana's platform and SLO dashboards,
   Alertmanager, container state/restarts, PostgreSQL connections, Redis memory,
   worker heartbeat, and durable job state.
4. Stop or restrict new writes at the proxy if integrity, tenant isolation, or
   payment correctness may be affected. Do not purge queues or edit billing rows.
5. Prefer reversible mitigation. Verify recovery using an unaffected tenant and
   synthetic data, then monitor for at least one alert evaluation window.

## Scenario procedures

### Database unavailable

- Confirm `PostgresUnavailable` separately from `PostgresExporterDown`; inspect
  container health, disk, connections, and PostgreSQL logs.
- Stop write traffic if readiness is failing. Do not repeatedly restart while a
  migration or restore is active.
- Restore connectivity or fail over using the deployment-owned database process.
  If integrity is uncertain, validate the latest encrypted backup in isolation.
- Verify migration head, `/api/ready`, authentication, tenant-scoped reads, one
  bounded write, worker completion, and billing counts before reopening traffic.

### Redis unavailable

- Distinguish `RedisUnavailable` from exporter loss. Inspect Redis health,
  persistence, memory, blocked clients, evictions, and network membership.
- Keep database-backed durable work authoritative; do not manually mark queued
  work complete. Restore Redis, then allow reconciliation actors to republish it.
- Verify worker heartbeat, authentication rate limiting, cache behavior, queue
  drainage, and exactly-once durable outcomes.

### Worker backlog

- Compare worker heartbeat, queued/running database rows, Redis queue lengths,
  failure counters, oldest queued age, CPU, memory, and PostgreSQL saturation.
- Pause nonessential producers if age or depth is growing. Scale only from the
  measured bottleneck and within AutoML slot and database-pool limits.
- Never purge a queue. Reconciliation is the supported recovery path. Confirm
  stable depth/age and terminal durable states before removing mitigation.

### Email provider failure

- Check `TransactionalEmailDeliveryFailures`, provider status, retry outcomes,
  and durable outbound-email rows using message IDs rather than addresses.
- Keep retries bounded; do not switch to capture mode in production. Fix provider
  credentials/DNS or fail over only to a pre-approved sender.
- Send verification, reset, invitation, and support probes to controlled inboxes;
  verify text/HTML, sender, reply-to, provider ID, metrics, and redacted logs.

### Paymob callback failure

- Check `PaymentWebhookFailures`, callback HTTP status, durable event state,
  worker failures, and Paymob's provider reference. Never log the full callback.
- Confirm HMAC configuration before replay. Use Paymob's signed replay mechanism;
  never construct an unsigned success event.
- Verify a repeated callback is idempotent and that entitlements change only
  after backend-authoritative verified success.

### Payment mismatch

- Freeze automatic entitlement changes for the affected company and preserve
  subscription, payment, invoice, webhook, and audit records.
- Compare amount, currency, provider transaction/order reference, integration,
  and final provider status. Do not edit history or grant access from a receipt.
- Resolve through a reviewed compensating operation, then verify payment history,
  subscription state, usage limits, and customer communication.

### Failed migration

- Keep the new application out of rotation. Capture the failing revision and
  database error; determine whether the migration transaction rolled back.
- Restore the prior compatible application image. Never run an untested live
  downgrade. Validate any downgrade against an isolated restored backup first.
- Correct forward with a new migration when practical; re-run empty-database and
  upgraded-database tests before retrying production.

### Disk full or filesystem pressure

- Check `ContainerFilesystemPressure`, database/Redis volumes, artifact and upload
  volumes, Docker storage, logs, and backup destination independently.
- Stop write-heavy work. Remove only classified disposable data under the
  retention policy; never delete database, Redis, upload, model, or backup files.
- Expand storage or move retained data safely, then verify persistence, backups,
  uploads, model reads, and alert recovery.

### High API latency

- Check `APILatencyDegradation`, p50/p95/p99 by route, in-flight requests,
  database connections/slow queries, Redis, container pressure, and upstreams.
- Rate-limit an abusive route or disable a failing optional integration. Scale
  only after identifying CPU, memory, connection, or worker contention.
- Verify p95 below 500 ms for the accepted workload and no corresponding 5xx rise.

### Model inference failure

- Identify the registered model version/alias, artifact availability, bounded
  input schema, prediction failure metric, and correlated error—never input data.
- Remove the failing alias from service or restore the last approved version.
- Validate with synthetic rows and confirm prediction audit/monitoring continuity.

### RAG ingestion failure

- Check dataset validation, extraction/chunking/embedding stages, queue age,
  `RAGIndexBuildFailures`, timeouts, artifact storage, and worker resources.
- Cancel only through the API; correct the source or dependency and create a new
  immutable version/build. Let reconciliation repair interrupted states.
- Verify ready state, tenant-scoped retrieval, citations, and no cross-tenant hit.

### Subscription incorrectly suspended

- Preserve subscription, payment, webhook, invoice, usage, override, and audit
  history. Confirm provider status and grace-period timestamps.
- Use only the audited entitlement override path for urgent temporary access; set
  an owner, reason, and expiry. Never patch a database row directly.
- Reconcile the authoritative lifecycle and verify all role and quota boundaries.

### Backup restore

- Follow `backup-and-restore.md`. Verify checksum/HMAC and decrypt only in an
  isolated access-controlled location.
- Run `scripts/restore/restore-validation.sh` before considering live recovery.
  Confirm migration head and all tenant, billing, auth, and document counts.
- Live overwrite needs an approved outage, explicit destructive flag, two-person
  review, and a tested rollback artifact.

### Security incident

- Invoke `incident-response.md`; preserve evidence and restrict access. Rotate or
  revoke affected credentials through their owner without exposing old values.
- Contain the affected route/tenant/integration. Do not destroy logs or rebuild
  compromised hosts until evidence is captured.
- Validate tenant isolation, sessions, webhook signatures, audit history, images,
  backups, and required notifications before recovery.

## Known monitoring limits before launch

Prometheus rules cover availability, latency, errors, worker failures, provider
failures, database/Redis connectivity and saturation, and container resource
pressure. Production is not operationally accepted until deployment owners add
an external Alertmanager receiver and prove delivery. Queue depth/oldest age and
backup success/freshness are not exported as Prometheus metrics yet; operators
must check them directly until those alerts are implemented and tested.

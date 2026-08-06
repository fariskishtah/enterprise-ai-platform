# Billing Phase 1 remediation operations

Phase 1 fixes three critical billing controls while leaving Paymob and production
payment collection disabled. It does not change prices, checkout correlation,
callback integration binding, capture semantics, or the recurring commercial
model.

## Platform-only billing authority

`billing.platform_operate` is absent from every tenant role, including Owner. A
user satisfies it only when the independent `users.is_platform_operator`
attribute is true. There is no tenant or public API that can set that attribute.

Platform access must be provisioned through the controlled database administration
process using a reviewed user UUID, change ticket, two-person approval, and
post-change verification. Remove it when the assignment ends. This is the
smallest safe mechanism supported by the current identity model; dedicated
workforce identity and just-in-time access remain future hardening work.

Override and replay routes include the target tenant UUID and query resources by
both tenant and resource identifier. Cross-tenant resources are not disclosed.
Every override mutation records actor, tenant, key, previous value, new value,
reason, timestamp, request ID, and correlation ID. Replay records the operational
reason and replay count. Denials go to structured security logs without payloads,
callback query strings, secrets, or customer content.

## Time-authoritative lifecycle

Entitlements evaluate status and timestamps together. Stored `active` is not
sufficient after `current_period_end`, `ended_at`, or `suspended_at`. In-grace
`past_due` is writable only until `grace_period_ends_at`. Period-end cancellation
remains active before its end and becomes cancelled when due. Expiry and downgrade
never delete customer data; they only prevent new paid or over-limit mutations.

The `reconcile_billing_lifecycle` actor uses a bounded due-row query,
`FOR UPDATE SKIP LOCKED`, and status/version compare-and-set. Concurrent or
repeated workers therefore create one transition and one audit event. Redis
scheduler fencing publishes at most one scheduled pass per interval per fleet.

```dotenv
BILLING_LIFECYCLE_RECONCILIATION_SCHEDULING_ENABLED=true
BILLING_LIFECYCLE_RECONCILIATION_INTERVAL_SECONDS=60
BILLING_LIFECYCLE_RECONCILIATION_BATCH_SIZE=100
```

Metrics and structured logs report scanned subscriptions, transitions, failures,
duration, and oldest stale lifecycle age.

## Webhook recovery state machine

```text
received -> queued -> processing -> processed
    |          |          |
    |          |          +-> failed -> queued (bounded backoff)
    |          +------------> queued (stale publication recovery)
    +-----------------------> queued (inbox reconciliation)

processing -> dead_letter (attempt limit)
processing -> quarantined (permanent validation mismatch)
failed/dead_letter -> queued (accepted validation and audited operational replay)
processed/quarantined -> terminal (never replayable)
```

The worker commits `processing_started_at` and increments `attempts` before
effects. Payment, subscription, invoice, audit, and final event state then commit
atomically. A crash leaves a recoverable lease. Transient failures store a bounded
category, sanitized message, and exponential-backoff `next_retry_at`. Permanent
payload, unknown-payment, amount, currency, unknown-state, and out-of-order
failures are quarantined without changing money or subscription state.

The recovery actor republishes stale queued events, reclaims stale processing,
publishes due failures, and dead-letters exhausted work. Duplicate publications
are safe because only `queued` can claim `processing`, while payment ordering and
the latest granting payment keep effects idempotent.

```dotenv
BILLING_WEBHOOK_MAX_RETRIES=5
BILLING_WEBHOOK_RETRY_BASE_SECONDS=30
BILLING_WEBHOOK_QUEUED_STALE_SECONDS=300
BILLING_WEBHOOK_PROCESSING_STALE_SECONDS=300
BILLING_WEBHOOK_RECOVERY_BATCH_SIZE=100
BILLING_WEBHOOK_RECOVERY_SCHEDULING_ENABLED=true
BILLING_WEBHOOK_RECOVERY_INTERVAL_SECONDS=60
```

Monitor queue depth, oldest queued age, oldest processing age, failed count,
dead-letter count, replay count, lifecycle failures, and stale lifecycle age.
Alert immediately on any dead letter, growing age, or repeated lifecycle failure.

## Safe replay

Before replay, reconcile the authenticated callback, target tenant, provider and
local amount/currency/reference, event order, and subscription state. Record an
incident reason, invoke the platform-only tenant-scoped endpoint once, then verify
the event and confirm payment, period, invoice, and latest granting payment did
not duplicate. Never edit payloads, reset payment state, delete events, or publish
an arbitrary queue message.

## Rollback and reconciliation

Migration `0032_billing_phase1_remediation` is additive. Its downgrade is only
for a failed pre-traffic migration. After Phase 1 traffic, retain the schema and
roll back to a compatible application image. Never delete webhook/audit rows,
queues, volumes, payments, subscriptions, overrides, or migration history.
The migration now refuses downgrade when any webhook or platform-operator
evidence exists. Migration `0031_entitlement_overrides` likewise refuses to drop
overrides, usage ledgers, or document quota support after entitlement,
subscription, or document evidence exists. Production remains roll-forward-only;
these guards are last-resort protection, not an approved downgrade procedure.

Before and after rollback, stop new checkouts while continuing verified callback
ingestion; compare event states/counts/ages; reconcile every succeeded payment to
its subscription period and invoice; verify due lifecycle transitions; and
preserve replay and override audit evidence.

`PAYMENT_PROVIDER` must remain `disabled` in production. Phase 1 does not make
the system ready for Paymob sandbox acceptance.

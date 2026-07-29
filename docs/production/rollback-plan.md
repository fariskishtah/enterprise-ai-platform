# Production rollback plan

## Decision triggers

Rollback when the candidate causes sustained fast SLO burn, tenant isolation or
data-integrity risk, incorrect payment/entitlement transitions, unrecoverable
worker backlog, or a migration incompatibility that cannot be safely forward-fixed
inside the approved incident window. The incident commander owns the decision.

## Preconditions

- Keep the prior immutable backend, worker, frontend, and proxy image digests.
- Record schema compatibility for both versions and keep a fresh encrypted,
  verified, off-host backup with its checksum/HMAC.
- Maintain deployment-owned configuration and secret versions; never copy secrets
  into rollback notes or command history.
- Test this plan against the same topology before release.

## Application rollback

1. Declare the incident, preserve bounded evidence, and restrict writes if data
   correctness is uncertain.
2. Record current image digests, Alembic revision, queue age/depth, database
   connections, durable nonterminal jobs, and payment webhook state.
3. Route traffic away from the candidate. Deploy the prior compatible application
   image set without changing database state.
4. Verify health/readiness, authentication/session refresh, tenant-scoped read and
   bounded write, worker completion, RAG read, billing status, metrics, and logs.
5. Reopen traffic gradually and monitor at least one fast-burn alert window.

## Schema or data recovery

Never downgrade or overwrite the live database as a reflexive rollback. First
restore the production backup into isolation, verify its checksum/HMAC and counts,
then test the exact application/schema combination. Prefer a reviewed forward fix.
If live restore is unavoidable, require a maintenance window, stopped writes,
two-person review, a second rollback artifact, the restore script's explicit
destructive flag, and post-restore reconciliation.

## Abort and completion criteria

Abort if the artifact identity is uncertain, schema compatibility is unproven,
backup verification fails, or recovery would overwrite newer valid payments.
Rollback completes only when customer-path smoke tests pass, alerts recover,
durable queues stabilize, billing and audit histories reconcile, and the incident
commander records the result. Preserve failed artifacts and evidence for review.

`rollback-runbook.md` remains the compact emergency checklist; this document is
the release-level decision and verification plan.

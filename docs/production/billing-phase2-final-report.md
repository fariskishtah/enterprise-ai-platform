# FactoryMind Billing Phase 2 final report

**Date:** 2026-08-03  
**Baseline:** deployed Billing Phase 1 at `7a3a211`  
**Deployment performed:** No  
**Production payment provider changed:** No; production remains disabled

## 1. Root cause of each blocker

1. Browser return correlation used a local UUID that Paymob's static return did
   not reliably supply. It now uses a per-checkout opaque state whose SHA-256
   hash, purpose, tenant binding, environment, target plan/quote, and expiry are
   persisted.
2. Callback authentication verified HMAC but did not bind the transaction to the
   configured integration, merchant owner, or sandbox/live contract. Those
   values and the supported source type are now normalized and fail closed.
3. `success=true` was mapped directly to `succeeded`. Provider decisions are now
   explicit; only a successful standalone payment or capture is
   `succeeded_eligible`. Authorization-only stays pending, and ambiguous success
   is quarantined for review.
4. Idempotency protected one key but did not order different keys. One company
   may now have only one open intent. A newer request supersedes the prior one;
   an eligible payment for a superseded or expired intent is quarantined and
   cannot change access.
5. Product copy described monthly subscription behavior although checkout made
   one-time Intentions. The only enabled commercial model is
   `prepaid_manual_renewal`; unsupported recurring mode fails startup.
6. No durable provider-truth comparison existed. Platform-only reconciliation
   now records append-only runs/results, supports dry-run, raises critical alerts
   for missing succeeded money records, and uses finance-approved compensating
   events rather than silent history rewrites.

## 2. Files changed

Backend contracts and persistence:

- `backend/app/billing/providers/base.py`
- `backend/app/billing/providers/paymob.py`
- `backend/app/billing/providers/factory.py`
- `backend/app/billing/providers/__init__.py`
- `backend/app/config/settings.py`
- `backend/app/models/billing.py`
- `backend/app/models/__init__.py`
- `backend/app/repositories/billing.py`
- `backend/app/schemas/billing.py`
- `backend/app/services/billing.py`
- `backend/app/services/billing_reconciliation.py`
- `backend/app/api/routes/billing.py`

Frontend and configuration:

- `frontend/src/api/billing.ts`
- `frontend/src/pages/PricingPage.tsx`
- `frontend/src/pages/billing/BillingCheckoutPage.tsx`
- `frontend/src/pages/billing/BillingOverviewPage.tsx`
- `frontend/src/pages/billing/BillingReturnPage.tsx`
- `frontend/src/pages/billing/BillingUi.tsx`
- `.env.example`
- `docker-compose.yml`

Tests and documentation:

- `backend/tests/test_billing_phase2_invariants.py`
- `backend/tests/test_billing_migration.py`
- `backend/tests/test_billing_provider_lifecycle.py`
- `backend/tests/test_paymob_provider.py`
- `frontend/e2e/billing.spec.ts`
- `docs/billing.md`
- `docs/production/environment-template.md`
- `docs/production/billing-phase2-remediation.md`
- this report

## 3. Migration added

`0033_billing_phase2_contracts` is additive and PostgreSQL-safe. It preserves all
payments and deterministically reduces legacy concurrent open attempts to the
newest open intent before creating the partial unique index. It adds return-state,
intent/supersession, expiry, provider-decision/binding, environment, and commercial
snapshots plus reconciliation runs/results. Downgrade refuses to discard evidence
when payment, webhook, or reconciliation traffic exists.

## 4. Return-correlation design

FactoryMind creates 256 bits of random opaque state, stores only its SHA-256 hash,
and sends the plaintext state only in that checkout's Paymob redirection URL. The
authenticated frontend posts it to `/billing/returns/resolve`; the backend hashes
it and checks tenant, purpose, and expiry before returning persisted payment state.
Missing, unknown, tampered, expired, or cross-tenant state cannot resolve. Browser
refresh is safe. Success, amount, status, plan, and tenant query values are ignored.

Polling uses exponential backoff capped at eight seconds and ends after a bounded
attempt count. The user can then retry status without creating another checkout.

## 5. Callback-binding design

After constant-time SHA-512 HMAC verification, the adapter validates provider,
integration ID, callback `owner` merchant ID, `is_live` environment, merchant
reference UUID, source type, amount, currency, provider occurrence time, ordering,
and duplicate identity. Invalid HMAC and all normalized contract mismatches are
durably quarantined with card-free safe payloads. HMAC values, query strings,
credentials, and card data are not stored or logged.

## 6. Capture/settlement eligibility policy

- refund and void/reversal outrank success;
- pending remains `pending`;
- a successful authorization without capture is
  `authorized_not_captured` and grants nothing;
- a successful standalone transaction or capture is `succeeded_eligible`;
- an otherwise successful but ambiguous combination is `under_review` and
  quarantined;
- only `succeeded_eligible` may activate or change paid access.

No unmodeled settlement field was invented. Provider reconciliation must be used
where the authenticated callback cannot prove the approved eligibility contract.

## 7. Checkout supersession policy

The database permits one open checkout intent per company, a rule stricter than
purpose/plan scoping. Same-key replay returns the same unexpired hosted checkout.
A new key creates a new intent and atomically supersedes the old one. Local expiry
prevents reuse. A superseded/expired paid result becomes manual review and does not
mutate subscription state. Local cancellation alone does not outrank a later
eligible provider event. Failed current plan changes clear matching pending-plan
state.

## 8. Commercial billing model

`BILLING_COMMERCIAL_MODEL=prepaid_manual_renewal` is the only supported mode.
Each eligible payment buys one fixed access period, and renewal requires another
checkout. No automatic collection or saved mandate is scheduled. Selecting
`provider_recurring_subscription` fails closed. Non-secret platform diagnostics
expose this posture.

## 9. Reconciliation model

`billing_reconciliation_runs` and `billing_reconciliation_results` retain the
provider/environment/idempotency key, actor, dry-run flag, finance approval
reference, outcomes, local/provider states, and compensating-event link. Outcomes
cover matched, missing sides, amount/currency/integration/environment/state
mismatches, manual review, and correction by compensating event. Repeated run keys
are idempotent. Only `billing.platform_operate` can execute the route; tenant Owner
and Admin roles remain denied.

The Paymob transaction-query implementation deliberately fails closed until its
exact query/authentication response has passed isolated sandbox acceptance. Local
validation uses the real comparison logic behind a deterministic provider client,
including malformed and provider-failure handling boundaries.

## 10. Frontend changes

The return page resolves opaque state, shows only backend truth, and provides
pending, verified, declined, cancelled, expired, refunded, reversed, and
under-review actions. Pricing, checkout, overview, and history now say prepaid
access period and new-checkout renewal, not auto-renewing subscription. Hosted URL
navigation is limited to HTTPS allowlisted Paymob hosts (plus same-origin local
preview). History shows checkout-intent state. Desktop and mobile screenshots were
reviewed in light and dark modes for pricing, billing overview, checkout, verified
payment, and under-review recovery. The final views had no horizontal overflow,
clipping, inaccessible contrast, or missing recovery action in the exercised
states.

## 11. Security controls

- browser redirects cannot grant access;
- callbacks and audited provider reconciliation are the only payment authorities;
- entitlement override, replay, diagnostics, and reconciliation remain platform
  operations;
- tenant scope is applied to return resolution and payment reads;
- checkout/receipt host policy is explicit and credential-free;
- contract mismatches and superseded payments quarantine instead of activating;
- no secrets or raw sensitive callback payloads were added to code, fixtures,
  screenshots, reports, or logs.

## 12. Tests added or updated

Coverage includes return hash/tenant/expiry, integration/environment/merchant
binding, capture eligibility, refund precedence, commercial fail-closed behavior,
supersession and expiry, safe quarantines, reconciliation outcome matrix,
provider/local missing results, dry-run/idempotency, audited compensation, and
platform-only access. Playwright covers redirect-value rejection, return recovery,
pending/declined/cancelled/expired/under-review states, duplicate submit prevention,
prepaid copy, mobile layout, dark mode, and accessibility.

## 13. Test results

- Backend full suite: **954 passed, 3 skipped**.
- Phase 2 invariant suite after final reconciliation changes: **18 passed**.
- Focused Phase 1/2 billing, lifecycle, entitlement, RBAC, provider, and migration
  suite: **75 passed**.
- Python lint: passed.
- Mypy: **305 source files, no issues**.
- Frontend ESLint: passed.
- Frontend TypeScript/Vite production build: passed.
- Billing Playwright suite: **17 passed**.
- Compose interpolation/configuration: passed with `PAYMENT_PROVIDER=disabled`.

## 14. PostgreSQL validation

PostgreSQL 16 with pgvector upgraded from an empty database to head and Alembic
reported no drift. A second database upgraded to 0032, received two existing open
payment records for one company, then upgraded to 0033: both rows were preserved,
one remained open, and one was superseded. The disposable container had no mounted
volume and was stopped/removed after validation.

## 15. Rollback plan

Do not downgrade after Phase 2 traffic. Keep payment collection disabled, roll the
application back to Phase 1 while retaining 0033, preserve webhook queues/events,
and capture counts for open, superseded, expired, under-review, and queued records.
After restoration, reconcile every in-flight provider transaction and process or
retain all compensating events. No payment, subscription, invoice reference,
webhook, audit, reconciliation, queue, migration, or database-volume deletion is a
valid rollback step.

## 16. Remaining Phase 3 gaps

- genuine provider invoices, tax documents, and authoritative receipt ingestion;
- partial refunds, disputes, chargebacks, settlement reporting, and finance UX;
- an accepted Paymob provider-transaction query contract;
- live/sandbox operational alert routing and finance approval identity workflow;
- optional provider recurring subscriptions, mandates, dunning/retries, provider
  cancellation synchronization, and accelerated sandbox renewal cycles;
- pricing versioning, proration, credits, and grandfathering.

## 17. Paymob sandbox readiness

**Not yet accepted as Paymob-sandbox ready.** The Phase 2 local contracts and
isolated PostgreSQL/browser acceptance pass, but no real Paymob sandbox credential,
callback, hosted checkout, capture, or provider-query acceptance run was performed.
The next step is a dedicated isolated sandbox using only sandbox data and the exact
variables in `docs/billing.md`. Production must remain disabled.

Paymob's current official guidance also states that backend callbacks—not browser
redirects—are the source of payment truth: [API integration flow](https://developers.paymob.com/paymob-docs/integration-paths/apis) and [callbacks/HMAC](https://developers.paymob.com/paymob-docs/developers/webhook-callbacks-and-hmac).

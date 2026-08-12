# FactoryMind billing and subscription audit

**Audit date:** 2026-08-03

**Audited production baseline:** `0d4cb24075eb4da930358edc67b6208ad363d9df`

**Audit type:** Repository and configuration-contract inspection only

**Production changes:** None
**Readiness decision:** **Not ready for Paymob sandbox acceptance or production payment enablement**

## Executive decision

FactoryMind has a credible payment foundation, but it is not yet a complete production subscription system.

The strongest existing controls are:

- the backend owns plan codes, EGP prices, and entitlements;
- checkout requests do not accept an amount, currency, company ID, or card data;
- checkout creation is tenant-scoped and protected by a database-backed idempotency key;
- Paymob transaction callbacks are authenticated with SHA-512 HMAC using constant-time comparison;
- the webhook worker checks local payment ID, provider, amount, currency, state ordering, and tenant ownership before applying a result;
- the browser return page reads authenticated backend state and ignores redirect `success` or status values;
- paid access is fail-closed when no provider or subscription is available;
- production configuration requires entitlement enforcement;
- callback persistence retains a hash and normalized card-free payload instead of the raw provider body.

The principal blockers are:

1. Owners and tenant Admins can grant their own entitlement overrides.
2. Grace expiry, scheduled cancellation, and other time-based transitions are not guaranteed to run and are not enforced directly by entitlement checks.
3. A successfully published webhook job can become permanently stuck if the broker loses the job or worker retries are exhausted.
4. The real Paymob browser return cannot reliably correlate the static redirect URL to the local payment UUID expected by the frontend.
5. Callback acceptance is not bound to the configured Paymob integration, sandbox/live mode, or a captured/settled payment semantic.
6. The implementation creates one-time Paymob Intentions. It does not integrate Paymob's recurring Subscriptions module, schedule renewals, or create provider subscriptions.

These are go-live blockers even though automated fixture tests pass.

## Scope and evidence

The audit inspected:

- `backend/app/billing/catalog.py`
- `backend/app/models/billing.py`
- `backend/app/repositories/billing.py`
- `backend/app/services/billing.py`
- `backend/app/services/entitlements.py`
- `backend/app/api/routes/billing.py`
- `backend/app/billing/providers/*`
- `backend/app/billing/queue.py`
- `backend/app/config/settings.py`
- migrations `0023` through `0031`
- billing, Paymob, lifecycle, entitlement, and migration tests
- `frontend/src/api/billing.ts`
- pricing, checkout, return, overview, invoice, history, and provider-event UI
- `frontend/e2e/billing.spec.ts`
- existing billing, lifecycle, entitlement, legal, and sandbox-acceptance documentation

The current Paymob documentation was used only to validate the external contract. Paymob states that backend callbacks are the source of truth and browser redirects are for user experience:

- [Paymob API integration flow](https://developers.paymob.com/paymob-docs/integration-paths/apis)
- [Paymob callbacks and HMAC](https://developers.paymob.com/paymob-docs/developers/webhook-callbacks-and-hmac)
- [Paymob checkout experiences](https://developers.paymob.com/paymob-docs/developers/checkout-experiences)
- [Paymob environments and required integration material](https://developers.paymob.com/paymob-docs/developers/quicklink-apis/overview)
- [Paymob payment features, including the separate Subscriptions module](https://developers.paymob.com/paymob-docs/payments-and-features)

No secret values, production data, Docker volumes, migrations, or production environment files were read or changed.

## Direct answer: can a browser redirect activate a subscription?

**No, not through any supported FactoryMind browser or API route at commit `0d4cb24`.**

The browser return page:

1. reads only `payment_id` from the URL;
2. calls tenant-scoped `GET /billing/payments/{payment_id}`;
3. displays and polls the persisted payment status;
4. ignores `success`, amount, plan, company, and status query values.

The only application assignment to subscription state `active` is in `BillingWebhookProcessor._apply_subscription_event()` after:

1. the public callback is HMAC-verified by the Paymob adapter;
2. a normalized event is durably persisted;
3. a UUID-only job is queued;
4. the worker locks the event and payment;
5. provider, local payment UUID, amount, currency, and ordering checks pass;
6. the normalized state equals `succeeded`.

Checkout creation produces `incomplete`, polling is read-only, and the tenant-admin reconciliation endpoint cannot transition a subscription to `active`.

This control is correct and must remain an invariant. It does not compensate for the other callback-validation and delivery gaps listed below.

## Pricing plans and prices

The backend static catalogue and migration `0030` define:

| Plan | Monthly price | Key limits |
| --- | ---: | --- |
| Starter | EGP 1,000 | 5 members, 1 factory, 25 machines, 100 documents, 2 GB, 500 monthly RAG queries, no model training |
| Professional | EGP 5,000 | 25 members, 5 factories, 250 machines, 2,500 documents, 25 GB, 5,000 monthly RAG queries, model training with concurrency 2 |
| Enterprise | EGP 10,000 | 100 members, 25 factories, 2,000 machines, 25,000 documents, 250 GB, 50,000 monthly RAG queries, model training with concurrency 10 and audit log |

Prices are stored in minor units and constrained to EGP in the database. The public pricing API returns the static catalogue, and checkout uses that same static price rather than a client value.

Gaps:

- The static catalogue is the runtime authority while `billing_plans` is also treated as an authority for active state and upgrade/downgrade comparisons. Existing database records are not synchronized by `_ensure_plan()` when catalogue prices change.
- `GET /billing/plans` does not actually query `billing_plans.is_active`; it always returns every static catalogue item.
- There is no price version, effective date, grandfathering, promotion, tax policy, or quote snapshot beyond the amount on an individual payment.
- The public legal disclosure remains explicitly unapproved. “Billed monthly” currently overstates the implementation because no automatic recurring collection exists.

## Subscription lifecycle

Persisted states are:

- `incomplete`
- `trialing`
- `active`
- `past_due`
- `suspended`
- `cancelled`
- `expired`

Implemented transitions include verified initial activation, manual renewal, paid plan change, failed renewal to grace, grace expiry to suspension, period-end and immediate cancellation, cancellation reactivation before period end, reactivation by new paid checkout, and latest-payment refund/reversal suspension.

Important limitations:

- Time-based reconciliation runs only during `GET /billing/subscription` or an explicit tenant-admin reconcile call. There is no scheduled lifecycle worker.
- `EntitlementService` reads the stored status without reconciling `current_period_end`, `grace_period_ends_at`, or `cancel_at_period_end`. A stale `active` or `past_due` row can therefore continue to authorize mutations after access should end.
- There is no trial creation or trial-end processor despite the `trialing` state.
- Renewal requires a user-created one-time checkout. No renewal scheduler, payment token, provider subscription, retry schedule, or dunning workflow exists.
- Failed plan-change and reactivation payments can leave `pending_plan_id` populated indefinitely.
- Multiple simultaneous checkouts are allowed. Successful callbacks for different payments can change the plan in provider-event order rather than checkout-intent order, and multiple payments can extend or replace access.
- A paid plan change charges the full target monthly amount and resets the period. There is no proration, credit, scheduled downgrade, or authoritative quote.
- Immediate cancellation ends local access without a provider refund or finance workflow.

## Models and migrations 0023-0031

### `0023_add_billing_foundation`

Creates plans, entitlements, provider customers, subscriptions, payments, invoice references, webhook events, usage counters, and billing audit events. It includes useful positive-money, EGP, uniqueness, period, and usage constraints.

### `0024_add_transactional_email`

Adds durable outbound email state. It does not connect billing transitions to payment confirmation, failure, invoice, or cancellation emails.

### `0025_add_email_verification`

Adds verification state and encrypted email payload metadata. No direct billing schema effect.

### `0026_add_six_role_rbac`

Introduces Owner/Admin roles. The later permission map gives both roles `billing.manage`; this is appropriate for ordinary tenant billing but unsafe for tenant-controlled entitlement overrides.

### `0027_add_team_invitations`

Creates invitations. Entitlement usage correctly counts unexpired pending invitations toward `team_members`.

### `0028_add_refresh_token_families`

Authentication-only migration with no billing state effect.

### `0029_harden_payment_events`

Adds checkout and idempotency identifiers, expected plan, hosted URL, provider event time, raw provider event identifier, and normalized safe payload. Unique constraints protect local checkout replay and exact provider event duplication.

### `0030_subscription_lifecycle`

Seeds three plans and quotas; adds one subscription per company, pending plan, latest granting payment, lifecycle timestamps, version, purpose, payment-linked invoices, and webhook tenant attribution.

Risks:

- The unique company-subscription constraint has no migration preflight or deterministic consolidation if earlier deployments contain multiple rows per company.
- Downgrade removes lifecycle columns but leaves the seeded plan and entitlement data behind.
- `version` is incremented but not used for optimistic concurrency; correctness currently depends on row locks.

### `0031_entitlement_overrides`

Adds tenant entitlement overrides, metering ledger idempotency, and document quotas.

Risks:

- Downgrade deletes all `documents` entitlements, including values that might have existed or been customized before the migration.
- Downgrade deletes the usage idempotency ledger and overrides, so it is not a safe operational rollback after traffic.

### Migration-chain conclusion

Billing migrations are interleaved with authentication and email migrations. Downgrading billing to `0022` would also remove transactional email, verification state, six-role RBAC, invitations, and refresh-token lineage. Migration downgrade must not be used as a billing application rollback.

The migration test upgrades to head and downgrades using SQLite. It does not provide PostgreSQL acceptance for indexes, row locks, constraints, concurrency, seed reconciliation, or production-volume upgrade behavior.

## Entitlements and real backend enforcement

Confirmed enforcement exists for:

- team members, including pending invitations;
- factories;
- machines;
- document count;
- document storage bytes;
- monthly RAG queries;
- model training access and concurrency;
- advanced reports;
- scheduled reports.

RAG metering uses an idempotency ledger and bounded atomic counter upsert. Resource capacity checks lock the subscription row, which serializes common tenant mutations within their request transaction.

Gaps:

- **Critical:** `/billing/admin/entitlement-overrides/{key}` requires only `billing.manage`. Owners and tenant Admins can enable restricted features or raise their own quotas. Existing tests explicitly exercise this self-service grant.
- `audit_log` is sold as an Enterprise feature but the audit endpoints do not invoke `require_feature("audit_log")`.
- Time policy is not checked by `_access_context()`, allowing stale active/grace state as described above.
- Enforcement is concentrated on known mutation routes; there is no automated route-to-entitlement coverage proving every new paid feature is protected.
- Override reasons are audited, but there is no approval workflow, separate platform-operator role, ticket reference, dual control, or immutable before/after snapshot.

## Usage tracking

Resource usage is calculated live. Monthly RAG queries are persisted in `usage_counters`, with `usage_ledger_events` protecting retry idempotency.

Gaps:

- There is no reconciliation job comparing counters with source-of-truth RAG request records.
- There is no reporting for failed/rejected usage attempts or idempotency-key collisions with different quantities.
- Calendar-month UTC periods may differ from a subscription billing period; that policy needs explicit commercial approval.
- Counter and ledger retention/archival policy is not defined.
- Usage APIs return snapshots but the frontend loads only the current view and does not expose period history.

## Checkout and payment attempts

Positive controls:

- backend plan and price resolution;
- hosted Paymob UI only;
- client-side duplicate-submit guard;
- database unique `(company_id, idempotency_key)`;
- safe retry classification for timeouts, 408, 429, and 5xx;
- tenant-scoped payment status and history.

Gaps:

- There is no single-open-checkout constraint per subscription/action.
- Different idempotency keys can create multiple chargeable attempts for the same plan/action.
- Hosted checkout URLs and pending payments have no local expiry.
- A provider-error retry reuses the payment but can be submitted with different billing contact data.
- The frontend TypeScript purpose union does not match backend values (`plan_change` and `reactivation`).
- The frontend accepts any HTTP(S) checkout URL returned by the backend; production configuration is trusted, but an explicit Paymob-host allowlist would reduce misconfiguration risk.

## Webhook verification, idempotency, and replay protection

Positive controls:

- documented transaction-field HMAC construction;
- constant-time signature comparison;
- exact-payload hash;
- database uniqueness and atomic enqueue claim;
- normalized card-free event payload;
- payment row lock;
- amount, currency, provider, and state-order validation;
- duplicate success does not extend a subscription twice;
- refund/reversal outrank success;
- raw card callback data is not persisted.

Critical gaps:

- The adapter does not compare callback `integration_id` with `PAYMOB_INTEGRATION_ID`.
- The adapter does not compare Paymob `is_live` with `PAYMENT_SANDBOX_MODE`.
- A callback with `success=true` is treated as paid without an explicit configured policy for authorization-only versus captured/settled transaction fields.
- Once an event is marked `queued`, duplicate callbacks cannot requeue it. If the broker acknowledges publication but loses the message, or the worker exhausts retries, the event can remain queued forever. There is no billing equivalent of the email reconciliation worker, no stale-processing recovery, no dead-letter state, and no privileged safe replay endpoint.

Additional gaps:

- The HMAC is supplied in the URL query and may be retained in proxy/access logs unless query redaction is configured.
- There is no provider API reconciliation for a missing callback.
- Partial refunds are treated as full refund state; refunded amount, disputes, chargebacks, settlement, and fees are not modeled.
- The callback event identity intentionally changes with payload content. This supports transaction state updates, but needs explicit tests for same-state payload variants and replay after retention/restore.

## Invoices, receipts, and payment history

Payment history is real local payment-attempt history and is tenant-scoped.

Invoice records are currently synthetic local references created after a successful callback:

- `provider_invoice_id` is `transaction:<provider transaction ID>`;
- `receipt_url` is not populated by the Paymob adapter;
- no provider invoice/receipt API is called;
- there is no tax invoice number, tax breakdown, legal entity data, PDF generation, credit note, or immutable invoice snapshot.

The UI label “Invoices & receipts” therefore overstates current capability. Pagination exists in the API, but the frontend always requests only the first 20 payments and invoices.

## Upgrade, downgrade, cancellation, reactivation, grace, and failed payments

| Operation | Current behavior | Readiness concern |
| --- | --- | --- |
| Upgrade | Full target-plan checkout; applies after success | No proration/credit; concurrent attempt ordering is undefined |
| Downgrade | Full target-plan checkout; resets period after success | No period-end scheduling or credit policy |
| Period cancellation | Local flag; reconciled after period end on billing read/admin call | No scheduled authoritative transition |
| Immediate cancellation | Ends local access immediately | No refund/provider action or finance approval |
| Reactivate scheduled cancellation | Clears local flag before end | Appropriate for current one-time model |
| Reactivate ended access | Requires new checkout | No provider subscription relationship |
| Renewal failure | Manual renewal failure enters grace | There is no automatic renewal attempt or retry schedule |
| Grace expiry | Reconcile changes `past_due` to `suspended` | Not guaranteed to run; entitlement checks do not enforce timestamp |
| Refund/reversal | Suspends if it targets latest granting payment | Partial refunds and disputes are not distinguished |

## Billing permissions and audit logs

`billing.manage` belongs to Owner and Admin. Engineer, Operator, Analyst, and Viewer are excluded. Backend endpoints derive tenant ID from the authenticated user rather than request data.

Positive audit coverage includes checkout request/creation/failure/cancel, subscription transitions, cancellation/reactivation, and entitlement override changes.

Gaps:

- Entitlement overrides need a platform-only permission separate from tenant billing management.
- Immediate cancellation and provider-event inspection may warrant Owner-only or explicitly delegated permissions.
- Backend tests do not comprehensively assert the role matrix for every billing endpoint.
- Audit events are mutable database rows without append-only/WORM retention, export signing, or external security-log forwarding requirements.
- Failed authorization attempts and denied billing mutations are not part of the billing audit trail.

## Frontend audit

Positive controls:

- public pricing loads backend catalogue data;
- checkout never collects card data;
- submission is synchronously guarded against repeat clicks;
- return UI ignores redirect success flags and polls authenticated local state;
- billing pages cover active, pending, failed, cancelled, refunded, reversed, suspended, expired, and grace states;
- history tables are keyboard-focusable and horizontally scrollable on mobile;
- non-billing roles are hidden/denied in frontend routing.

Gaps:

- A real return URL is not correlated to the local payment. `BillingReturnPage` requires `?payment_id=<local UUID>`, while the provider receives one static `PAYMENT_SUCCESS_URL`. The implementation does not demonstrate that Paymob returns a `payment_id` parameter with that name.
- Existing `.env.example` and production documentation use `/billing/success` and `/billing/failure`, but the implemented route is `/settings/billing/return`.
- `PAYMENT_FAILURE_URL` is required by settings but is not sent in the Intention payload; `redirection_url` always uses `PAYMENT_SUCCESS_URL`.
- Return polling has no timeout or exponential backoff.
- “I left checkout” stops the local UI at cancelled even though a later verified success may correctly supersede local abandonment.
- Billing overview fails as a single workspace if any one of its subscription, plan, entitlement, history, audit, or provider-event requests fails.
- Pricing and billing language needs approved recurring, cancellation, refund, tax, and invoice disclosures.

## Test coverage assessment

Existing backend suites cover catalogue values, SQLite migration round trip, checkout idempotency, provider failure, HMAC, amount/currency mismatch, duplicate and concurrent webhook claims, out-of-order states, refund/reversal precedence, lifecycle transitions, quota boundaries, metering concurrency, tenant isolation, and API response contracts.

Existing frontend E2E tests cover pricing, overview, themes, hosted redirect behavior, fake redirect success, pending/failed/cancelled/refund/reversal states, duplicate submit, cancellation/reactivation, downgrade routing, role denial, and mobile layout.

Important limitations:

- Every provider and frontend payment flow is mocked or fixture-backed.
- The repository's own sandbox report states that live sandbox acceptance is blocked and that no hosted checkout or external callback was attempted.
- Frontend E2E does not run through the real backend or Paymob.
- Migration acceptance is SQLite-only, not PostgreSQL.
- No tests cover tenant denial for entitlement overrides; current tests assert the unsafe grant.
- No test proves expiry is enforced without visiting a billing endpoint.
- No test covers lost queued webhook recovery or retry exhaustion.
- No test covers real redirect correlation.
- No test covers integration ID, live/test mode, authorization/capture semantics, partial refund, dispute, settlement, invoice receipt, or provider reconciliation.
- No test covers competing successful checkouts for the same subscription.
- No test covers a second automatic billing cycle because automatic recurrence is absent.

## Paymob integration readiness

**Current classification: automated adapter foundation only; real sandbox acceptance not achieved.**

The Intention API payload, Unified Checkout construction, and HMAC algorithm are plausible and tested against fixtures. That is not evidence that the configured Paymob merchant account, payment method, redirect behavior, callback schema, HMAC secret, transaction semantics, refunds, or recurring module work end to end.

Production payment enablement must remain blocked until the critical gaps are fixed and a credential-backed sandbox acceptance run succeeds.

## Ranked gap list

### Critical

1. **Tenant self-service entitlement escalation:** Owner/Admin can grant paid overrides using `billing.manage`.
2. **Access may outlive policy timestamps:** no scheduled lifecycle reconciler and entitlement checks do not reconcile timestamps.
3. **Webhook delivery has a permanent-stuck window:** no queued/processing event reconciler, dead-letter handling, or safe replay.
4. **Real browser return correlation is incomplete:** static redirect configuration does not supply the local `payment_id` required by the frontend.
5. **Callback trust is not sufficiently scoped:** configured integration ID, sandbox/live mode, and capture/settlement semantics are not validated.
6. **No recurring subscription collection:** no Paymob subscription, saved payment mandate, automatic renewal, retry, or dunning integration exists despite monthly-subscription presentation.

### High

1. Multiple open payments can charge and update one subscription in callback arrival order.
2. `audit_log` is sold as an entitlement but is not enforced at audit endpoints.
3. Invoice/receipt records are synthetic and not provider or legally approved invoices.
4. Partial refunds, disputes, chargebacks, settlement, fees, and credit notes are not modeled.
5. Immediate cancellation has no provider/refund/finance workflow.
6. Paid plan changes have no proration, credit, scheduled downgrade, or approved disclosure.
7. No provider reconciliation exists for missing callbacks or local/provider drift.
8. Failed plan changes/reactivations and pending payments are not expired or cleaned up.
9. Billing lifecycle emails are defined as types but are not emitted by payment transitions.
10. Billing rollback through Alembic is unsafe because the chain is interleaved and downgrades are lossy.
11. No real Paymob sandbox or PostgreSQL acceptance has been completed.
12. Pricing, renewal, tax, invoice, cancellation, and refund legal content remains unapproved.

### Medium

1. Runtime static catalogue and database plan records can drift; active-plan state is ignored by the public API.
2. Frontend payment-purpose types do not match backend values.
3. HMAC query values require explicit access-log redaction.
4. Return polling is unbounded and lacks backoff.
5. Frontend history is fixed to the first 20 rows.
6. Receipt URLs lack an explicit HTTPS/provider-host policy.
7. Payment purpose, invoice status, webhook status, and audit result have incomplete database constraints.
8. Sandbox/live mode is validated at startup but otherwise unused by the Paymob adapter.
9. Provider customer and provider subscription fields are unused.
10. The documented callback and browser-return paths are inconsistent with deployed routing.

### Low

1. `PAYMOB_API_KEY` and `PAYMOB_IFRAME_ID` are retained but unused by Unified Checkout.
2. `/usage`, `/usage/breakdown`, and `/limits` are aliases returning the same snapshot.
3. Several database constraints are not mirrored in ORM metadata, increasing test/schema drift risk.
4. Plan descriptions and commercial labels have no versioned content source.

## Recommended implementation sequence

1. **Keep payments fail-closed.** Leave `PAYMENT_PROVIDER=disabled` outside a dedicated sandbox environment.
2. **Add failing invariant tests first.** Cover tenant override denial, expiry without billing-page visits, lost webhook recovery, redirect correlation, integration/mode validation, capture semantics, and competing checkouts.
3. **Separate privileges.** Introduce a platform-operator-only entitlement-override permission. Decide whether cancellation, provider-event inspection, and reconciliation are Owner-only or delegated tenant capabilities.
4. **Make lifecycle time authoritative.** Reconcile inside entitlement access checks and add a scheduled, idempotent subscription lifecycle worker with observable batches.
5. **Harden the webhook inbox.** Add stale queued/processing reclamation, bounded retry metadata, failed/dead-letter state, safe administrative replay, and queue-depth/age alerts.
6. **Bind Paymob callbacks.** Validate integration ID, test/live mode, expected transaction semantics, supported payment method, and exact merchant/account contract before success is eligible to activate.
7. **Fix return correlation.** Use a backend-generated per-payment return URL or translate Paymob's returned merchant/special reference to a tenant-scoped local payment before rendering. Do not trust redirect success.
8. **Choose the commercial recurring model.** Either integrate Paymob's Subscriptions module and provider lifecycle, or explicitly sell non-recurring prepaid monthly access. Do not label one-time manual renewals as automatic subscriptions.
9. **Control concurrent attempts.** Define one open plan-change/renewal attempt, supersession rules, quote expiry, and deterministic handling of multiple successful charges.
10. **Implement finance semantics.** Add provider reconciliation, actual receipts/invoices, partial refunds, chargebacks/disputes, settlement status, credits, and cancellation/refund policy.
11. **Complete frontend and legal work.** Correct routes/types/copy, add bounded polling and pagination, and obtain finance/legal approval.
12. **Run isolated sandbox acceptance.** Use dashboard-issued test credentials externally, public HTTPS callbacks, real hosted checkout, success/decline/abandon/refund/replay tests, and reconciliation.
13. **Canary before production.** Enable only for an internal tenant with limits, alerts, daily reconciliation, and a tested kill switch.

## Exact Paymob sandbox environment contract

Do not put values in source control or this report. The backend and billing worker must receive the same configuration.

### Required by current code

```dotenv
ENVIRONMENT=staging
PAYMENT_PROVIDER=paymob
PAYMENT_SANDBOX_MODE=true
PAYMOB_SECRET_KEY=<dashboard-issued-test-secret-key>
PAYMOB_PUBLIC_KEY=<dashboard-issued-test-public-key>
PAYMOB_HMAC_SECRET=<dashboard-issued-test-hmac-secret>
PAYMOB_INTEGRATION_ID=<enabled-test-payment-method-integration-id>
PAYMOB_BASE_URL=https://accept.paymob.com
PAYMOB_WEBHOOK_URL=https://<sandbox-host>/api/billing/webhooks/paymob
PAYMENT_SUCCESS_URL=https://<sandbox-host>/settings/billing/return
PAYMENT_FAILURE_URL=https://<sandbox-host>/settings/billing/return
PAYMENT_CURRENCY=EGP
PAYMENT_HTTP_TIMEOUT_SECONDS=10
BILLING_WEBHOOK_QUEUE_NAME=billing-webhooks
BILLING_WEBHOOK_MAX_RETRIES=5
BILLING_GRACE_PERIOD_DAYS=7
BILLING_INCOMPLETE_EXPIRY_HOURS=24
BILLING_SUSPENSION_EXPIRY_DAYS=30
BILLING_ENTITLEMENTS_ENFORCED=true
```

`ENVIRONMENT=production` cannot be combined with `PAYMENT_SANDBOX_MODE=true`, which is a correct guard. Use an isolated staging/sandbox deployment with separate database, Redis namespace/queue, domain, and test tenant.

### Required application infrastructure

These are existing platform requirements rather than Paymob credentials, but sandbox billing will not function without them:

- `DATABASE_URL` for the isolated sandbox database at migration head;
- `REDIS_URL` shared by backend and worker;
- `APP_PUBLIC_URL` and `API_BASE_URL` for the sandbox host;
- `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, secure cookie settings, and HTTPS;
- a running worker consuming `BILLING_WEBHOOK_QUEUE_NAME`.

### Not required by the current Unified Checkout adapter

- `PAYMOB_API_KEY` is defined for legacy/other Paymob APIs but is not used by `POST /v1/intention/`.
- `PAYMOB_IFRAME_ID` is defined but unused because the application uses Unified Checkout.

### Important redirect warning

The two redirect variables are currently required by settings, but the values above are **not sufficient for acceptance** until return correlation is implemented. The current frontend requires a local `payment_id`; a static URL without that value renders “missing payment reference.” `PAYMENT_FAILURE_URL` is not sent to Paymob by the current adapter.

## Billing and payment production acceptance criteria

All criteria are mandatory unless explicitly removed by an approved product decision.

### Security and authority

- Only an HMAC-verified, integration-matched, environment-matched, captured/settled eligible provider event can mark a payment succeeded or activate/change paid access.
- Browser redirects, query values, client polling, support tools, and tenant-admin reconciliation cannot activate a subscription.
- Tenant Owners/Admins cannot grant entitlement overrides unless an explicitly approved commercial policy delegates a narrowly bounded capability.
- Secrets, HMAC values, client secrets, raw callbacks, PAN, tokens, and cardholder data are redacted from logs, traces, audit metadata, and error reports.

### Checkout and money

- Backend catalogue amount/currency exactly match the Paymob Intention and callback.
- Duplicate submissions and retries create one payment intention per idempotency key.
- Open checkout concurrency and supersession rules are deterministic.
- Success, decline, timeout, abandonment, and provider outage have clear recoverable states.
- The real Paymob return reliably resolves the local tenant-scoped payment without trusting result flags.

### Webhooks and recovery

- Exact and concurrent duplicates process once.
- Replays and out-of-order state changes cannot regress or double-extend access.
- Invalid HMAC, wrong integration, wrong environment, wrong amount/currency, unsupported transaction semantics, and unknown payment references do not mutate payment/subscription state.
- Broker failure, lost job, worker crash, retry exhaustion, and stale processing recover through an idempotent reconciler or enter an alerted dead-letter state.
- Administrators have an audited, bounded, idempotent safe-replay procedure.

### Subscription lifecycle

- The recurring commercial model is implemented and approved: provider subscription or explicitly non-recurring prepaid access.
- At least two consecutive sandbox billing periods or accelerated provider cycles are verified.
- Renewal success/failure, retry/dunning, grace, suspension, recovery, cancellation, and reactivation reconcile with provider truth.
- Time-based access changes occur without a user visiting billing pages.
- Upgrade/downgrade timing, proration/credit, simultaneous attempts, and cancellation/refund semantics are approved and tested.

### Entitlements and usage

- Every sold feature and quota has backend enforcement tests, including audit log.
- Production cannot disable enforcement.
- Metered usage is idempotent, concurrency-safe, reconcilable, and aligned with the approved billing period.
- Downgrades preserve data but prevent new over-limit mutations.

### Finance and customer records

- Payment history reconciles to Paymob transactions.
- Invoices/receipts are genuine provider or legally compliant FactoryMind documents with immutable numbers and amounts.
- Partial/full refunds, reversals, chargebacks, disputes, fees, settlements, taxes, credits, and failed collections have defined records and workflows.
- Required transactional billing emails are queued once and contain accurate non-marketing information.

### Testing and operations

- PostgreSQL migration and concurrency tests pass at production-like volume.
- Backend, frontend, integrated E2E, accessibility, and mobile suites pass.
- Real Paymob sandbox success, decline, abandonment, duplicate callback, invalid HMAC, refund/void, missing callback, and reconciliation acceptance passes.
- Dashboards and alerts cover callback age, queue age, failure/dead-letter count, payment/subscription mismatch, reconciliation differences, and provider latency/error rate.
- A canary, kill switch, rollback rehearsal, and finance reconciliation sign-off are complete.

## Rollback requirements

1. Use application rollback and feature flags, not Alembic downgrade, after any billing traffic.
2. The kill switch must stop new checkouts while continuing to accept, authenticate, persist, and safely process/reconcile callbacks for already-created payments.
3. Drain or pause workers in a controlled way; never delete queues, database rows, or Docker volumes.
4. Deployments must remain forward-schema compatible with the last known good application image.
5. Take a verified database backup before billing schema changes, including restore-time evidence.
6. Preserve all payment, webhook, subscription, invoice, usage-ledger, and audit identifiers through rollback.
7. Never convert a succeeded payment or active subscription by bulk rollback without provider reconciliation and finance approval.
8. Use compensating records/transitions rather than editing or deleting historical money events.

## Reconciliation requirements

Reconciliation must run before rollout, during canary, after rollout, after rollback, and on a recurring schedule.

At minimum compare:

- Paymob transaction ID, merchant/special reference, integration, live/test mode, amount, currency, success/capture/refund/reversal state, and event time;
- local payment ID, provider IDs, status, purpose, amount, currency, and provider occurrence time;
- subscription plan, latest granting payment, status, period, grace, cancellation, and version;
- invoice/receipt reference and refund/credit state;
- webhook event status, attempt count, age, duplicate relation, and last error.

Operational rules:

- unknown provider transactions and unknown local succeeded payments are Critical alerts;
- queued/processing events older than a defined threshold are reclaimed or dead-lettered with audit evidence;
- amount, currency, integration, environment, or tenant-reference mismatches are quarantined and never auto-applied;
- reconciliation corrections are idempotent and append audited compensating events;
- finance owns approval for money-state corrections; engineering does not silently rewrite history;
- daily totals by status and currency must balance between Paymob, payments, invoices, refunds, and subscription grants.

## Final conclusion

FactoryMind correctly prevents a browser redirect from activating a subscription and has a sound start on backend-owned checkout and verified callback processing. It should remain payment-disabled in production.

Real Paymob readiness can be claimed only after the Critical gaps are fixed and the full credential-backed sandbox acceptance criteria above pass. The existing fixture tests and adapter structure are necessary evidence, but not sufficient acceptance.

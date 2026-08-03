# Billing and Paymob checkout

The backend owns the Starter (EGP 1,000), Professional (EGP 5,000), and
Enterprise (EGP 10,000) monthly catalogue in
`backend/app/billing/catalog.py`. Prices are stored in minor units. The checkout
API accepts a plan code and billing contact details; it never accepts an amount,
currency, company identifier, or card data.

## Supported payment boundary

`POST /billing/checkouts` requires `billing.manage`, a unique
`Idempotency-Key`, and billing contact data. When `PAYMENT_PROVIDER=paymob`, the
server creates a Paymob Intention and returns the Paymob Unified Checkout URL.
The browser is redirected to Paymob, which exclusively collects card or wallet
credentials. A disabled or failing provider returns an explicit error and never
creates a successful payment.

This follows Paymob's current official flow:

- [API integration overview](https://developers.paymob.com/paymob-docs/integration-paths/apis)
- [Intention creation](https://developers.paymob.com/paymob-docs/developers/intention-apis/create-intention)
- [Unified Checkout versus Pixel](https://developers.paymob.com/paymob-docs/developers/checkout-experiences)
- [Callbacks and HMAC](https://developers.paymob.com/paymob-docs/developers/webhook-callbacks-and-hmac)
- [Official integration wizard and test tools](https://wizard.paymob.com/)

The adapter uses `POST /v1/intention/` with `Authorization: Token
<PAYMOB_SECRET_KEY>`, the configured integration ID, backend-resolved amount,
`EGP`, a local payment UUID in `special_reference`, notification URL, and
redirection URL. It constructs `/unifiedcheckout/` from the returned client
secret and the public key. `PAYMOB_API_KEY` remains available for older Paymob
APIs but is not used by the current Intention call. `PAYMOB_IFRAME_ID` is
retained for accounts using the older iframe flow; this application deliberately
uses Unified Checkout instead.

## Callback trust and state ordering

`POST /billing/webhooks/paymob?hmac=...` is public by necessity but verifies the
documented SHA-512 transaction HMAC before persistence. The HMAC value is read
from the callback query parameter. Invalid signatures return 403.

Paymob's raw transaction ID is stored separately from a deterministic event ID.
Only a hash of the raw callback and a normalized, card-free payload are stored.
An atomic status update gives exactly one duplicate request permission to queue
the event. Delivery states are `received`, `queued`, `processing`, `processed`,
`failed`, `dead_letter`, and `quarantined`. Processing leases, retry timestamps,
bounded attempts, sanitized errors, stale-work reconciliation, and an audited
platform-only replay path prevent durable events from remaining silently stuck.
The worker locks each event and payment while applying it. Duplicates and replays
are idempotent.

Payment state precedence is monotonic:

`pending < failed < succeeded < provider cancellation < reversed < refunded`

A higher-trust provider success can override a local cancellation, while a late
failure cannot overwrite success. Refund and reversal flags supersede success.
Amount or currency mismatches are retained as quarantined security evidence and do
not modify the payment. Unknown callback types are rejected.

Paymob currently documents transaction callbacks for success or decline. A user
who abandons hosted checkout therefore remains pending until the authenticated
client explicitly calls `POST /billing/payments/{id}/cancel`. Redirect query
parameters are presentation-only and never activate payment or subscription
state.

## Configuration

The provider is fail-closed with `PAYMENT_PROVIDER=disabled`. A Paymob
deployment needs:

- `PAYMENT_PROVIDER=paymob`
- `PAYMOB_SECRET_KEY`, `PAYMOB_PUBLIC_KEY`, and `PAYMOB_HMAC_SECRET`
- `PAYMOB_INTEGRATION_ID`
- `PAYMOB_MERCHANT_ID` (the callback `owner` identifier for the sandbox merchant)
- `PAYMOB_BASE_URL=https://accept.paymob.com` for Egypt
- public `PAYMOB_WEBHOOK_URL`, `PAYMENT_SUCCESS_URL`, and
  `PAYMENT_FAILURE_URL`
- `PAYMENT_SANDBOX_MODE=true`, `PAYMENT_CURRENCY=EGP`, and the exact hosted
  checkout/source allowlists

Phase 2 uses `BILLING_COMMERCIAL_MODEL=prepaid_manual_renewal`. Each eligible
payment buys one fixed access period. No automatic collection, saved mandate,
or recurring provider subscription is scheduled. Selecting
`provider_recurring_subscription` fails startup until that separate integration
has passed recurring sandbox acceptance.

The exact isolated sandbox variables are:

```dotenv
PAYMENT_PROVIDER=paymob
PAYMENT_SANDBOX_MODE=true
PAYMENT_CURRENCY=EGP
PAYMOB_SECRET_KEY=<sandbox-secret-key>
PAYMOB_PUBLIC_KEY=<sandbox-public-key>
PAYMOB_HMAC_SECRET=<sandbox-hmac-secret>
PAYMOB_INTEGRATION_ID=<sandbox-payment-method-integration-id>
PAYMOB_MERCHANT_ID=<sandbox-callback-owner-id>
PAYMOB_BASE_URL=https://accept.paymob.com
PAYMOB_WEBHOOK_URL=https://<isolated-api-host>/billing/webhooks/paymob
PAYMENT_SUCCESS_URL=https://<isolated-app-host>/settings/billing/return
PAYMENT_FAILURE_URL=https://<isolated-app-host>/settings/billing/return
PAYMOB_ALLOWED_CHECKOUT_HOSTS=["accept.paymob.com"]
PAYMOB_SUPPORTED_SOURCE_TYPES=["card"]
BILLING_COMMERCIAL_MODEL=prepaid_manual_renewal
BILLING_CHECKOUT_EXPIRY_MINUTES=30
BILLING_RETURN_REFERENCE_EXPIRY_MINUTES=60
```

`PAYMOB_API_KEY` and `PAYMOB_IFRAME_ID` are not used by the Phase 2 Intention
checkout. No provider-transaction query endpoint is claimed ready; the Paymob
reconciliation adapter deliberately fails closed until its query contract passes
isolated sandbox acceptance.

The approval-gated isolated-host procedure is documented in the
[Paymob sandbox deployment runbook](production/paymob-sandbox-deployment.md).
- `PAYMENT_CURRENCY=EGP`
- `PAYMENT_SANDBOX_MODE=true` with test keys, or `false` with live keys

Settings reject known live key prefixes in sandbox mode, known test key prefixes
in live mode, sandbox mode in production, non-HTTPS production URLs, incomplete
Paymob credentials, and currencies other than EGP. Paymob documents that test
and live credentials use the same regional base URL; the credential mode is the
environment boundary.

## Persistence

Migration `0023_add_billing_foundation` created plans, entitlements, provider
customers, subscriptions, payments, invoice references, webhook events, usage
counters, and billing audit records. Migration
`0029_harden_payment_events` adds checkout/idempotency references, expected plan,
hosted URL, provider ordering time, raw callback identifier, and normalized safe
event data. Provider transaction and checkout identifiers are uniquely
constrained. Company-scoped billing models participate in the ORM tenant guard.

Migration `0030_subscription_lifecycle` seeds the backend catalogue and adds one
subscription per company, pending plan changes, the exact payment that last
granted access, lifecycle timestamps/versioning, payment purpose, payment-linked
invoice references, and tenant attribution for webhook inspection.

## Subscription lifecycle

Checkout creates or reuses the company's subscription in `incomplete` state.
Only a verified, amount-and-currency-matched provider success changes it to
`active`. Redirect parameters and client polling never grant access. Supported
states are:

`incomplete`, `trialing`, `active`, `past_due`, `suspended`, `cancelled`, and
`expired`.

Successful renewals extend from the later of the current period end or provider
event time. A failed renewal enters `past_due` for
`BILLING_GRACE_PERIOD_DAYS` (default 7); reconciliation then suspends access.
Incomplete checkouts expire after `BILLING_INCOMPLETE_EXPIRY_HOURS` (default
24), and long-running suspension expires after
`BILLING_SUSPENSION_EXPIRY_DAYS` (default 30). Entitlements evaluate time policy
directly. Temporal reconciliation also runs on subscription reads, through the
explicit tenant-admin endpoint, and through a scheduled row-locked actor.

Upgrade and downgrade checkouts record `pending_plan_id`; the current plan stays
authoritative until verified payment. This release intentionally resets the
billing period on a successful paid plan change—there is no invented proration.
Cancellation defaults to period end. The explicitly requested `immediate` mode
ends access now. Reactivation before period end removes scheduled cancellation;
reactivating a cancelled, expired, or suspended subscription requires a new
verified checkout.

Refund, reversal, or provider cancellation suspends only when it targets the
payment that currently grants access. A later success for that terminal payment
cannot reactivate the subscription. Every transition and privileged billing
action writes a tenant-scoped, card-free audit event.

## Authenticated billing APIs

- `GET /billing/subscription`
- `POST /billing/subscription/upgrade` and `/downgrade`
- `POST /billing/subscription/cancel` and `/reactivate`
- `GET /billing/history/payments` and `/history/invoices`
- `GET /billing/admin/events` and `/admin/provider-events`
- `POST /billing/admin/subscription/reconcile`

All authenticated records are derived from the access token's `company_id`.
Company IDs are never accepted from route parameters or request bodies. Billing
domain errors use a stable `{code, message}` response detail.

## Entitlements and metering

`EntitlementService` is the central decision point for subscription access,
catalogue limits, tenant overrides, current resource counts, and metered usage.
Production startup rejects `BILLING_ENTITLEMENTS_ENFORCED=false`; local and test
environments may explicitly leave enforcement disabled for legacy fixtures.

The service enforces team members (including pending invitations), factories,
machines, document count, exact stored bytes, monthly grounded RAG queries,
model-training access and queued/running concurrency, advanced reports, and
report schedules. RAG increments use a per-tenant idempotency ledger and an
atomic upsert bounded by the effective monthly limit. Monthly counters use UTC
calendar periods and retain prior periods as history.

`active`, `trialing`, and in-grace `past_due` subscriptions may mutate within
their limits. Suspended subscriptions remain visible but read-only; incomplete,
cancelled, and expired subscriptions are blocked. Downgrading never deletes
resources. Existing over-limit resources remain readable while new creation is
denied with:

```json
{
  "code": "quota_exceeded",
  "current": 1,
  "maximum": 1,
  "period_start": null,
  "period_end": null,
  "recommended_plan": "professional"
}
```

Tenant admins can inspect `/billing/entitlements`, `/billing/usage`,
`/billing/usage/breakdown`, `/billing/limits`, and
`/billing/recommendation`. Tenant roles, including Owner and Admin, cannot manage
manual exceptions. Overrides require an explicitly provisioned platform operator
and use `/billing/platform/tenants/{company_id}/entitlement-overrides/{key}`.
Every mutation requires a reason and records before/after values plus request
correlation. Migration `0031_entitlement_overrides` adds the exceptions and
metering ledger; `0032_billing_phase1_remediation` separates platform authority
and adds webhook recovery state. See the
[Phase 1 operations guide](production/billing-phase1-remediation.md).

## Billing management frontend

`/pricing` renders the public backend catalogue. Owners and Admins can use
`/settings/billing` to inspect the current subscription and effective access,
usage thresholds, plan comparison, payment/invoice history, billing audit events,
and durable provider callback status. Other roles receive the dedicated 403 view;
navigation visibility is only a convenience and does not replace backend
`billing.manage` authorization.

Plan selection opens an authenticated billing-contact form and then redirects to
the backend-returned Paymob Unified Checkout URL. A synchronous submission guard
and stable `Idempotency-Key` cover rapid duplicate actions. Card or wallet data is
never collected by the application.

`/settings/billing/return?state=...` submits only the opaque return state to the
authenticated, tenant-scoped resolver. The server verifies its hash, purpose,
tenant binding, and expiry before the page polls persisted payment state. The page
renders pending, succeeded, declined, cancelled, expired, refunded, reversed, and
under-review recovery states. Any `success`, status, price, plan, company, or
payment identifier included in the redirect URL is ignored. Pending checkout
abandonment is recorded only through the authenticated cancellation API.

The management view has state-specific past-due/grace, suspended/read-only,
scheduled-cancellation, incomplete, cancelled, and expired guidance. It never
shows proration because no authoritative proration quote exists. Receipt links
appear only when returned by the invoice API.

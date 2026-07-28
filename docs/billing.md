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
the event. The worker locks each event and payment while applying it. Exact
duplicates are no-ops; safe retries can reclaim an event if broker publication
failed.

State precedence is monotonic:

`pending < failed < cancelled < succeeded < reversed < refunded`

A higher-trust provider success can override a local cancellation, while a late
failure cannot overwrite success. Refund and reversal flags supersede success.
Amount or currency mismatches are retained as ignored security evidence and do
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
- `PAYMOB_BASE_URL=https://accept.paymob.com` for Egypt
- public `PAYMOB_WEBHOOK_URL`, `PAYMENT_SUCCESS_URL`, and
  `PAYMENT_FAILURE_URL`
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

Subscription activation and recurring lifecycle behavior belong to Phase F. A
verified Paymob payment currently changes only the payment record; it does not
silently create an active subscription.

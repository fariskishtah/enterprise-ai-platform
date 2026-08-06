# Phase E Paymob validation evidence

## Automated evidence

The provider contract and lifecycle suites cover:

- exact backend-priced Intention requests and hosted checkout URL construction;
- no accepted or transmitted card fields;
- invalid plans and companies;
- client-supplied amount/currency rejection;
- callback amount/currency mismatch rejection;
- SHA-512 HMAC success and failure;
- exact and concurrent duplicate protection;
- success, decline, pending, refund, reversal, and unknown callback types;
- out-of-order state suppression;
- timeout and retryable HTTP classification;
- fail-closed provider errors and migration round trips.

Run:

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_paymob_provider.py \
  tests/test_billing_provider_lifecycle.py \
  tests/test_billing_catalog.py \
  tests/test_billing_migration.py
```

## Historical manual sandbox procedure

This procedure applies only to an isolated non-production environment. Current
production configuration must remain `PAYMENT_PROVIDER=disabled`; use the
isolated Sandbox runbook for the supported workflow.

1. In the Paymob dashboard, select test mode, enable the intended Egypt payment
   method, and copy its test Secret Key, Public Key, Integration ID, and HMAC
   secret. Do not use live keys.
2. Expose the backend callback over HTTPS and configure Paymob's transaction
   processed callback to
   `https://<test-api>/billing/webhooks/paymob`. Use the same value for
   `PAYMOB_WEBHOOK_URL`.
3. Set `PAYMENT_PROVIDER=paymob`, the four test credential values,
   `PAYMOB_BASE_URL=https://accept.paymob.com`, `PAYMENT_CURRENCY=EGP`, and
   `PAYMENT_SANDBOX_MODE=true`. Set HTTPS success/failure browser URLs.
4. Upgrade the database through `0031_entitlement_overrides`, restart the backend and
   worker, and confirm both are healthy.
5. Sign in as an Owner or Admin and call `POST /billing/checkouts` with a fresh
   `Idempotency-Key`, a catalogue plan code, and valid billing contact details.
   Confirm the response amount exactly matches `GET /billing/plans` and its URL
   is on the configured Paymob host.
6. Open the returned Unified Checkout URL. Use a currently published sandbox
   card from Paymob's [official integration wizard](https://wizard.paymob.com/).
   Confirm card data is entered only on Paymob's page.
7. Complete a successful test. Confirm one `billing_webhook_events` row reaches
   `processed`, its raw transaction ID is present, the local payment reaches
   `succeeded`, and the subscription becomes active only after this verified event.
8. Repeat with Paymob's current decline test case. Confirm the payment reaches
   `failed`, with no success or subscription activation.
9. Use Paymob's webhook testing tool to resend the identical success callback
   concurrently. Confirm both HTTP responses are prompt, only one event is
   processed, and the payment remains unchanged. Alter the HMAC and confirm 403.
10. Begin a checkout, abandon the hosted page, then call the authenticated local
    cancel endpoint. Confirm `cancelled`; confirm redirect parameters alone do
    not change payment state.
11. From the Paymob sandbox dashboard, refund or void a successful transaction
    where the enabled method supports it. Confirm the callback advances the
    local payment to `refunded` or `reversed`; then replay an older failure and
    confirm it is ignored as out of order.
12. Review backend and worker logs. They may contain local UUIDs, event types,
    lifecycle status, and safe error codes, but no API keys, HMAC secret, client
    secret, full callback, PAN, or cardholder data.

## Verification boundary

The integration and sandbox-safe automated fixtures are complete. No Paymob
credentials are stored in this repository. Until dashboard-issued test/live
credentials are supplied outside source control, manual sandbox and live
provider verification remain blocked; the application reports provider
unavailability rather than fabricating success.

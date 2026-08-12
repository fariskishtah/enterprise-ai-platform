# FactoryMind launch commercial model

Phase 3 product recommendation, 2026-08-11. This document does not approve
prices, change production configuration, or authorize live payment collection.

## Recommended launch model

Launch with one evaluation path, one self-service paid offer, and one
sales-assisted offer. Do not add more public tiers until real usage and support
costs justify them.

| Offer | Customer and value | Implemented limits to reuse | Support and billing | Upgrade path |
| --- | --- | --- | --- | --- |
| Evaluation / Trial | A manufacturing lead validating one site and the core monitoring, documents, and grounded AI journeys | Reuse Starter limits: 5 users, 1 factory, 25 machines/assets, 100 documents, 2 GB, 500 monthly AI assistant queries; no model training or advanced reports | Public demo immediately; a time-boxed assisted trial only after trial provisioning exists. No card and no automatic conversion | Owner chooses Professional or contacts sales before expiry |
| Professional | A growing manufacturing team operating several sites with AI-assisted workflows | Current Professional limits: 25 users, 5 factories, 250 machines/assets, 2,500 documents, 25 GB, 5,000 monthly AI assistant queries, 2 concurrent training jobs, advanced reports, and 10 schedules | Standard email support; current implementation is one prepaid month with manual renewal | Self-service renewal or plan change; Enterprise requires sales contact |
| Enterprise | A larger or governed estate needing scale, audit history, onboarding, and commercial terms | Current Enterprise limits are a baseline, not a promise: 100 users, 25 factories, 2,000 machines/assets, 25,000 documents, 250 GB, 50,000 monthly AI assistant queries, 10 concurrent training jobs, advanced reports, 100 schedules, and audit log | Contact sales; contract, support response, invoicing, tax, settlement, and any custom override require approval | Sales-assisted quote and an approved activation path |

The product has a `trialing` subscription state and generic period-expiry logic,
but no signup-to-trial provisioning or explicit reminder/conversion journey. A
new tenant has no subscription and enforced access is blocked. Therefore
FactoryMind must not advertise a self-service free trial yet. The minimal launch
path is an assisted evaluation; a real trial can later reuse Starter
entitlements instead of adding a fourth limit matrix.

## Existing catalogue prices

The repository currently defines EGP 1,000 Starter, EGP 5,000 Professional, and
EGP 10,000 Enterprise for one prepaid monthly access period. These values are
backend-authoritative and checkout ignores client-supplied amounts.

The values should remain unchanged in code until Product, Finance, and Legal
approve positioning, tax presentation, support cost, AI unit economics, and
Enterprise quoting. They should not be treated as approved launch prices. In
particular, a fixed self-service Enterprise price conflicts with the recommended
contact-sales model.

## Current real-money flow

1. An authenticated Owner or Admin selects a backend catalogue plan. FactoryMind
   creates a tenant-scoped, idempotent payment attempt using the server-owned EGP
   amount.
2. FactoryMind sends the amount, currency, plan line item, billing contact, local
   reference, and callback/return URLs to Paymob's Intention API.
3. The browser opens Paymob Unified Checkout. Paymob collects payment details,
   performs authentication, and processes the payment. FactoryMind does not
   collect or store PAN, CVV, wallet credentials, or a reusable payment mandate.
4. Browser return data is display-only. An HMAC-authenticated callback, bound to
   the expected integration, merchant owner, environment, amount, currency, and
   local reference, is the payment authority.
5. A capture-eligible success activates one prepaid month exactly once. A local
   subscription, entitlement state, payment history, audit evidence, normalized
   card-free callback data, and a local payment/invoice reference are stored.
6. Paymob holds/processes the customer funds and settles them to the merchant
   account under the merchant's Paymob agreement and configured settlement
   destination. FactoryMind does not calculate or execute merchant settlement.

This matches Paymob's documented hosted-checkout flow: the hosted page handles
payment details, backend callbacks are the source of truth, and HMAC validates
callback integrity. See the official [API integration flow](https://developers.paymob.com/paymob-docs/integration-paths/apis),
[checkout overview](https://developers.paymob.com/paymob-docs/developers/checkout-experiences),
and [callback/HMAC overview](https://developers.paymob.com/paymob-docs/developers/webhook-callbacks-and-hmac).

### Recovery behavior

- Decline/cancellation/expiry grants no access and offers a new checkout.
- A pending or delayed callback keeps the payment pending; the return page polls
  persisted state and lets the user check again without charging again.
- Closing the browser does not cancel a provider-completed payment; the callback
  can still activate it.
- One tenant may have only one unresolved checkout. Idempotency reuses the same
  attempt; a distinct newer attempt supersedes the old one. A paid superseded or
  locally expired attempt is quarantined for finance review rather than changing
  access.
- Durable webhook recovery and provider reconciliation can repair a missing or
  delayed callback without trusting the browser.
- Renewal is manual. Every successful checkout buys one calendar month. There is
  no saved mandate, automatic retry/dunning, Paymob subscription, or automatic
  renewal in the current implementation.

## Entitlement contract

The backend enforces team members (including pending invitations), factories,
machines/assets, document count, document storage bytes, monthly grounded RAG
queries, model-training availability and concurrency, advanced reports, and
scheduled reports. Audit log availability exists in the catalogue. Downgrade
does not delete resources: existing over-limit data remains readable and new
creation/use is denied. Only platform operators can create audited entitlement
overrides.

## Live Paymob readiness

**PAYMOB LIVE TECHNICAL READY: NO.**

The checkout, authenticated callback, exactly-once activation, recovery, and
Sandbox paths are implemented, but production intentionally rejects
`PAYMENT_PROVIDER=paymob`. Enabling it requires a separate reviewed code/config
change after the operator and commercial gates below. Production must remain
disabled until that decision.

### Code gaps

- Replace the explicit production fail-closed invariant only in a separately
  approved live-payment change, while retaining a rapid payment kill switch.
- Run live-mode contract tests with the exact approved integration, callback
  owner, source type, capture semantics, and public HTTPS origins.
- Accept and operationalize the live transaction-inquiry/reconciliation contract
  against the merchant account; do not rely only on callbacks.
- Add genuine provider invoice/tax-document ingestion and finance-facing
  settlement, fee, partial-refund, dispute, and chargeback records/workflows.
- Keep manual prepaid renewal, or separately implement and accept Paymob
  recurring subscriptions, mandates, retries, dunning, and cancellation sync.

### Operator actions outside the repository

- Complete Paymob merchant onboarding/business verification and obtain explicit
  go-live approval. Paymob's official overview lists a merchant account,
  Dashboard access, completed business verification, live credentials,
  integration IDs, webhook, and success/failure URLs as prerequisites:
  [Paymob integration overview](https://developers.paymob.com/paymob-docs/developers/quicklink-apis/overview).
- Have Paymob enable the intended live Egypt payment method(s), and bind the
  exact live integration and callback owner to the FactoryMind merchant account.
- Issue/store live Secret/Public/API credentials and HMAC secret in the approved
  production secret manager; configure no values in source control.
- Register the production HTTPS webhook and success/failure return URLs in the
  Paymob Dashboard and verify HMAC callbacks end to end.
- Confirm merchant settlement bank/account, schedule, fees, refund/void rights,
  tax invoicing, and finance reconciliation ownership with Paymob. Settlement is
  provider/merchant-account work, not a FactoryMind database action.
- Obtain Product/Finance/Legal approval for prices, taxes, prepaid renewal,
  cancellation/refund language, customer terms, invoice treatment, and support.
- Execute an approval-gated live canary for an internal tenant, with limits,
  monitoring, finance reconciliation, and a tested disable switch before broader
  availability.

## Phase 3 decision

The billing engine is suitable for a simple prepaid paid-SaaS launch after the
listed commercial, finance, legal, and live-operator gates. The recommended
initial public offer is evaluation, Professional, and Enterprise/contact sales.
Production payment collection remains disabled.

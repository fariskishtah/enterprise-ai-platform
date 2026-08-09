# Billing payment verification

## Impact

An authenticated callback may be waiting, quarantined, retrying, or dead-lettered,
leaving a captured provider payment without local activation. Production payment
collection must remain disabled until webhook delivery, reconciliation, and external
alert delivery are operationally accepted.

## Symptoms

- `PaymentWebhookFailures`, `PaymentWebhookBusinessQuarantine`,
  `PaymentVerificationStalled`, or `PaymentProviderReconciliationAttention` fires.
- The customer remains on the payment-verification screen and is told not to retry.
- Durable webhook events are failed, quarantined, or dead-lettered.

## Dashboard and queries

Use the `billing-operations` dashboard. Direct safe queries are:

```promql
sum by (outcome) (increase(billing_webhook_ingest_total[15m]))
sum by (outcome) (increase(billing_webhook_processing_latency_seconds_count[15m]))
billing_webhook_events
max(billing_payment_oldest_pending_age_seconds)
max(billing_subscription_oldest_incomplete_age_seconds)
sum by (outcome) (increase(billing_provider_reconciliation_attempts_total[15m]))
```

Do not place callback bodies, signatures, checkout URLs, customer data, credentials,
or full provider/payment identifiers in queries, tickets, or chat.

## Immediate checks

1. Confirm backend, worker, PostgreSQL, and Redis health.
2. Confirm the worker is consuming the billing queue and the recovery scheduler runs.
3. Classify the alert as crypto quarantine, business quarantine, processing failure,
   aged unresolved payment, or reconciliation failure.
4. Keep duplicate checkout prevention active; do not ask the customer to pay again.

## Diagnosis

- Missing or invalid HMAC is a terminal crypto quarantine. Do not replay it.
- Owner, integration, environment, amount, currency, or reference mismatch is a
  business quarantine. Investigate with safe metadata and authenticated provider
  inquiry; do not rewrite the callback.
- Retry/dead-letter outcomes indicate a persisted worker-side failure even when the
  Dramatiq actor returned normally after recording the failure.
- Provider inquiry must match the exact local reference, order, amount, currency,
  integration, environment/account identity, source type, and timestamp semantics.

## Mitigation

Restore the failed dependency or callback worker first. Use only the audited bounded
webhook-recovery or provider-reconciliation path. A compensating event is allowed only
from exact authenticated provider truth and must remain idempotent. Never activate a
subscription from the browser redirect, a copied callback body, or an operator guess.

## Escalation

Escalate immediately when a crypto-valid callback has an identity or money mismatch,
provider inquiry is ambiguous/unavailable, a dead letter persists, more than one local
payment could match, or entitlement state differs from the authoritative payment.
Production activation also requires a real external Alertmanager receiver and proven
delivery; the checked-in local null receiver is not sufficient.

## Verification

1. The callback is accepted or safely quarantined exactly once.
2. Processing or reconciliation reaches one durable terminal outcome.
3. Payment, subscription, entitlement, invoice, and audit state agree.
4. Duplicate callbacks and reconciliation runs create no duplicate side effects.
5. Pending/incomplete ages and failure counters stop increasing or return to zero.
6. A controlled non-production alert reaches the external on-call receiver.

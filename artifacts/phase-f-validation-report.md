# Phase F subscription lifecycle validation

Date: 2026-07-29

## Delivered

- One lockable, versioned subscription per tenant.
- Incomplete checkout state with verified-callback-only activation.
- Renewal periods, failed-renewal grace, suspension, cancellation, and expiry.
- Paid upgrade/downgrade with the current plan preserved until success.
- Period-end and explicit immediate cancellation plus safe reactivation.
- Refund/reversal/provider-cancellation precedence tied to the granting payment.
- Tenant-scoped payment, invoice/receipt, audit, and provider-event history.
- Machine-readable billing errors and admin reconciliation visibility.
- Migration `0030_subscription_lifecycle` with catalogue/entitlement seed data.

## Automated evidence

Full backend regression suite:

```text
897 passed, 3 skipped
```

Dedicated Phase F lifecycle suite, including authenticated API contracts:

```text
7 passed
```

Static validation:

```text
ruff: all checks passed
mypy: success (billing lifecycle sources)
alembic upgrade/check/downgrade: passed in focused migration test
```

The only emitted warnings are existing third-party MLflow/Pydantic deprecation
warnings. No real Paymob credential claim is made; live/sandbox provider
validation remains credential-gated and must never be represented as success
without an authenticated provider callback.

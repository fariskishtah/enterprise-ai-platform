# Billing and subscriptions

The backend owns the Starter (EGP 1,000), Professional (EGP 5,000), and
Enterprise (EGP 10,000) monthly catalogue and exact quotas in
`backend/app/billing/catalog.py`. Prices are stored in minor units; clients must
never submit an authoritative amount, currency, or company identifier.

Migration `0023_add_billing_foundation` adds plans, entitlements, provider
customers, subscriptions, payments, invoice references, webhook events, usage
counters, and billing audit records. Unique provider identifiers support future
idempotent processing. The public `/billing/plans` endpoint and `/pricing` page
show only this catalogue.

Hosted checkout, Paymob credentials, HMAC verification, webhook state machines,
portal management, enforcement, invoices, and production payment emails are not
implemented or enabled. Do not configure a production merchant account against
this revision. The required next step is a provider adapter plus sandbox tests
for invalid signatures, duplicates, concurrency, success/failure, upgrade,
downgrade, cancellation, grace periods, tenant isolation, and usage limits.

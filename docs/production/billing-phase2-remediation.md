# Billing Phase 2 remediation design

Phase 2 keeps `PAYMENT_PROVIDER=disabled` in production and adds no credentials.
It makes browser return correlation, provider callback eligibility, checkout
ordering, the prepaid commercial contract, and reconciliation explicit before an
isolated Paymob sandbox acceptance run.

## Schema proposal

Migration `0033_billing_phase2_contracts` is additive. Payments receive an opaque
return-reference hash and expiry, checkout-intent state and supersession link,
quote/environment/commercial snapshots, and the normalized provider decision and
binding identifiers. Reconciliation runs and results are append-only evidence.

The active checkout invariant is one open intent per company. A different valid
request supersedes the former intent while retaining both payment records. A paid
superseded or expired intent enters manual review and cannot mutate subscription
access. A local cancellation does not override a later eligible provider event
unless that checkout was superseded.

Return references are random, single-purpose values. Only their SHA-256 hashes are
stored. The Paymob intention receives a per-checkout redirection URL containing
the opaque state. The authenticated frontend posts that state to the backend;
the backend hashes it, enforces expiry and tenant scope, and returns only persisted
payment state. Redirect success, status, amount, currency, plan, and tenant values
have no authority.

## Provider decision policy

The Paymob fields already authenticated by the transaction HMAC are interpreted
as follows:

- refund and void/reversal flags outrank every success flag;
- pending remains pending;
- a successful authorization without capture remains
  `authorized_not_captured`;
- a successful standalone payment or capture is `succeeded_eligible`;
- a successful combination that proves neither standalone payment nor capture is
  `under_review` and quarantined;
- only `succeeded_eligible` may grant paid access.

Every accepted callback is also bound to the configured integration ID, merchant
owner ID, sandbox/live mode, source type, local reference, amount, and currency.
Only normalized, card-free fields are retained.

## Commercial model

Phase 2 supports `prepaid_manual_renewal` only. Each eligible payment buys one
fixed access period. No automatic collection, saved mandate, or recurring Paymob
subscription is implied. Selecting `provider_recurring_subscription` fails closed
until the separate provider lifecycle, retry/dunning, cancellation synchronization,
and accelerated sandbox-cycle contract is implemented and accepted.

## Reconciliation and corrections

The reconciliation boundary consumes authenticated provider transaction truth
through a provider client interface. Runs support dry-run, are platform-operator
only, record per-payment outcomes, and never overwrite event history. A money-state
correction requires an explicit finance approval reference and creates an audited
compensating provider event; the normal webhook processor applies that event.

Real Paymob retrieval remains deliberately unavailable. The repository does not
contain an accepted Paymob transaction-list endpoint, authentication scheme,
pagination contract, bounded date-window semantics, rate-limit behavior, or a
provider-query representation of source type and merchant/payment bindings.
`PaymobPaymentProvider.list_reconciliation_transactions` therefore fails closed,
diagnostics report the query contract as unaccepted, and failed runs cannot be
reused as apparent successful reconciliations. Production payment activation is
blocked until that external contract is accepted and covered by provider-query
tests.

## Rollback

Rollback is an application rollback to Phase 1 while retaining migration `0033`.
The new columns and reconciliation tables are forward-compatible and contain
security/audit evidence. Do not downgrade the database after Phase 2 traffic,
delete payment or event rows, or remove reconciliation evidence. Before rollback,
keep payment collection disabled, stop new checkout creation at the application
layer, drain or safely retain webhook jobs, capture reconciliation counts, and
reconcile every in-flight/open/superseded/under-review payment after restoration.

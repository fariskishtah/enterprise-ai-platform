# Entitlement and usage enforcement

`EntitlementService` is the only plan-policy decision point. It combines the
server catalogue, current subscription state, actual tenant resource counts,
monthly metering, and audited unexpired overrides. Production configuration
cannot disable enforcement.

The service protects member invitations and acceptance, factories, machines,
documents, exact document-storage bytes, grounded RAG requests, training access,
training concurrency, reports, and scheduled reports. Write paths call the
service before mutation; monthly RAG usage uses a transactionally bounded UPSERT
and an idempotency ledger so concurrent retries cannot double-charge usage.

| Subscription state | Read access | New mutations |
| --- | --- | --- |
| `trialing`, `active` | Full | Allowed within limits |
| `past_due` within grace | Full | Allowed within limits |
| `suspended` | Existing resources | Denied (read-only) |
| `incomplete`, `cancelled`, `expired` | Existing policy-scoped data | Paid mutations denied |

Downgrades never delete existing data. If current usage exceeds the new limit,
the workspace remains readable and creation is blocked until usage falls or the
plan changes. Quota failures contain `code`, `current`, `maximum`, period bounds,
and a recommended plan. Manual overrides require a reason, can expire, remain
company-scoped, and always create a billing audit record.

Tenant administrators can inspect effective policy through `/billing/entitlements`,
`/billing/usage`, `/billing/usage/breakdown`, `/billing/limits`, and
`/billing/recommendation`. The override and administrative inspection APIs require
`billing.manage`.

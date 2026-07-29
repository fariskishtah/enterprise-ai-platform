# Production incident response

## Severity

| Severity | Definition | Initial response target |
| --- | --- | --- |
| SEV-1 | Active security/tenant breach, data integrity risk, payment corruption, or total service outage | 15 minutes |
| SEV-2 | Major customer workflow unavailable, sustained SLO burn, provider or worker outage without corruption | 30 minutes |
| SEV-3 | Degraded or isolated behavior with a safe workaround | Next staffed hour |
| SEV-4 | Non-urgent defect or operational improvement | Backlog with owner |

Targets are operational assumptions, not customer-facing commitments. Legal and
support must approve any contractual response times.

## Roles and lifecycle

- The incident commander owns severity, decisions, timeline, and handoffs.
- The operations lead diagnoses and mitigates. A separate reviewer approves any
  live restore, schema change, manual entitlement override, or credential rotation.
- The communications lead sends approved internal/customer updates and records
  notification decisions. The security/privacy lead joins any confidentiality,
  integrity, credential, or regulatory event.

Declare and open a UTC timeline; capture alert, release, impact, affected region
or tenant count, and known-good time. Contain first, preserve evidence, mitigate
reversibly, verify from the customer path, monitor, then resolve. Do not call an
incident resolved while durable queues, billing reconciliation, or audit records
remain inconsistent.

## Evidence and privacy

Store bounded logs, correlation IDs, image digests, configuration fingerprints,
provider references, migration revision, metrics, and commands in the approved
incident system. Redact tokens, cookies, addresses, card data, callback bodies,
customer documents, prompts, and model inputs. Record evidence custody and access.

## Communications

For SEV-1, update stakeholders at least every 30 minutes; for SEV-2, hourly until
stable. State confirmed impact, mitigation, next update, and uncertainty. Do not
speculate about root cause or legal obligations. Legal/privacy owners decide on
customer, regulator, processor, and law-enforcement notification.

## Closure

Require customer-path verification, recovered alerts/SLOs, drained or stable
queues, reconciled payments/subscriptions, and an explicit incident-commander
decision. Complete a blameless review within five business days for SEV-1/2 with
root cause, contributing controls, detection gaps, actions, owners, and dates.

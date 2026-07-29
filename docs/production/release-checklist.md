# Production release checklist

Every item needs dated evidence, owner, reviewer, and result. `BLOCKED` is not a
pass. Never reuse local capture, mock-provider, or contract-test evidence as proof
of a real external integration.

## Release candidate

- [ ] Git tree is clean; reviewed commit/tag and immutable image digests recorded.
- [ ] Backend tests, frontend lint/type/build, Playwright, and Compose validation pass.
- [ ] Images rebuild from locks and security/container scans meet exception policy.
- [ ] Empty database migrates to Alembic head; encrypted backup restores in isolation.
- [ ] Health/readiness, auth, tenant isolation, worker actors, metrics, logs, traces,
      dashboards, and browser console are validated in the candidate environment.
- [ ] k6 smoke and normal thresholds pass; spike/stress/soak results and capacity
      limits are reviewed against the target customer workload.
- [ ] AutoML, dataset, RAG, and email schedulers have unique middleware types and
      no duplicate processing warning.
- [ ] DNS, certificate chain/hostname/expiry, HTTPS redirect, proxy headers, secure
      cookies, trusted hosts/CORS, public links, callback URL, and OpenAPI policy pass.
- [ ] Rollback image set, restoration artifact, owner, and maintenance procedure are ready.

## External acceptance and operations

- [ ] Real transactional email matrix passes from production-owned sender to
      controlled inboxes, including retry and terminal failure.
- [ ] Real Paymob sandbox success, failure/cancel, signed callback, replay, history,
      receipt reference, and frontend return flow pass.
- [ ] Encrypted backup is copied to deployment-owned off-host immutable storage;
      retention, restore identity, RPO/RTO, and alert delivery are proven.
- [ ] External Alertmanager receiver sends warning and critical test notifications
      to the on-call path; inhibition and resolution notifications are verified.
- [ ] Queue depth/oldest-age and backup failure/freshness alerts are implemented,
      fired deliberately, received externally, and linked to the production runbook.
- [ ] Legal placeholders are replaced with counsel-approved versioned documents;
      required acceptance/audit behavior is implemented and reviewed.
- [ ] Security exceptions are unexpired, owned, reviewed, and accepted by the
      authorized risk owner. Incident contacts and escalation paths are current.

## Go/no-go

Production approval requires every applicable item above. The release commander
must record classification, evidence links, accepted risks, rollback trigger,
monitoring window, and two-person approval before changing traffic.

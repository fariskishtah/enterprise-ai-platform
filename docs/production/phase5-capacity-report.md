# Phase 5 capacity report

Date: 2026-08-11

## Status

Phase 5 remediation passed against the owned local Compose project
`ai-manufacturing-staging-validation`. Production was not contacted or
modified, external AI calls and Paymob traffic were disabled, and persistent
Docker volumes were retained.

The launch target is met for a bounded initial rollout: 25 concurrent mixed
users sustained 0% errors with p50 67 ms, p95 239 ms, and p99 355 ms. Read and
retrieval workloads passed at 50 concurrent users. Mixed 50 is the measured
degradation point (p95 1.24 seconds), while auth 25 is the auth-specific
degradation point (p95 1.94 seconds). Escalation stopped at the first failed
threshold for each scenario.

This is a local production-topology capacity bound, not a benchmark of the
production host. A production-equivalent canary must confirm that the host can
provide the configured CPU and memory allocation before widening rollout.

## Remediation

- Raised the backend limit from 0.5 CPU/1 GiB to 4 CPUs/1.5 GiB while retaining
  one Uvicorn process for safe application lifecycle and Prometheus behavior.
- Moved secure Argon2 verification to a four-thread bounded executor so login
  no longer blocks the async event loop. Password hashing parameters were not
  weakened.
- Collapsed the executive dashboard's sequential aggregate queries into one
  database round trip.
- Configured an explicit SQLAlchemy pool (size 10, overflow 5, timeout 5
  seconds, recycle 1,800 seconds) and added bounded pool/exhaustion metrics.
- Added phase-level auth latency metrics for user lookup, password verification,
  and session issue.
- Replaced the shared RAG identity with reusable, owner-isolated load identities
  and one deterministic knowledge base per identity. Setup, steady-state, and
  teardown traffic are reported separately, and logout cleanup is deterministic.
- Kept the default two-second think time so the harness exercises the real rate
  limit instead of bypassing it.

## Post-remediation results

| Scenario      | Level |  req/s |    p50 |    p95 |    p99 | Errors | Result              |
| ------------- | ----: | -----: | -----: | -----: | -----: | -----: | ------------------- |
| API           |    25 | 101.56 | 7.8 ms | 119 ms | 548 ms |     0% | pass                |
| API           |    50 | 182.12 |  19 ms | 283 ms | 668 ms |     0% | pass                |
| API           |   100 | 192.41 | 230 ms | 788 ms | 1.05 s |     0% | stop: API p95 gate  |
| Auth cycle    |    10 |  22.25 | 112 ms | 1.44 s | 1.53 s |     0% | pass                |
| Auth cycle    |    25 |  40.00 | 291 ms | 1.94 s | 2.14 s |     0% | stop: auth p95 gate |
| DB reads      |    50 | 157.84 |  48 ms | 458 ms | 913 ms |     0% | pass                |
| DB reads      |   100 | 148.70 | 326 ms | 1.24 s | 1.63 s |     0% | stop: latency       |
| RAG retrieval |    25 |  12.56 | 112 ms | 597 ms | 758 ms |     0% | pass                |
| RAG retrieval |    50 |  24.83 |  43 ms | 428 ms | 639 ms |     0% | pass                |
| Mixed         |    10 |   5.59 |  79 ms | 138 ms | 210 ms |     0% | pass                |
| Mixed         |    25 |  13.26 |  67 ms | 239 ms | 355 ms |     0% | pass                |
| Mixed         |    50 |  28.69 | 177 ms | 1.24 s | 1.37 s |     0% | stop: latency       |

Request rate includes setup and teardown where applicable; latency gates use
steady-state application requests and exclude health/readiness probes.

Fifty owner-isolated documents were processed and indexed during deterministic
fixture seeding, and the worker queue returned to zero. The existing bounded
three-job local worker acceptance remained passing; no paid inference or
payment-provider call was made.

## Resource behavior

- Backend CPU reached about 101% on Docker's one-core percentage scale during
  API 100, within the four-CPU cap; mixed 50 was sampled around 62%.
- Backend memory peaked at approximately 330 MiB of the 1.5 GiB limit.
- PostgreSQL peaked at 17 observed connections across the stack. No pool
  exhaustion was recorded; the application pool permits at most 15 concurrent
  backend connections.
- Redis reported 24 clients, zero blocked clients, and no worker backlog.
- All isolated staging services remained healthy with zero restarts.

## Capacity decision

- Safe sustained concurrency: 25 mixed users at the default two-second think
  time.
- Safe burst concurrency: 50 for API, DB-read, and owner-isolated RAG workloads;
  50 mixed users are not sustained-safe.
- Tested degradation point: mixed 50; auth-specific degradation starts at 25;
  API/DB degradation starts at 100.
- Initial customer estimate: a bounded pilot of approximately 5-10 customer
  organizations with up to 25 simultaneous active operators in aggregate,
  subject to production-host resource parity and normal workload shape.
- Scaling trigger: mixed p95 above one second, auth p95 above 1.5 seconds, error
  rate above 2%, backend CPU sustained above 70% of its allocation, pool
  exhaustion, or sustained active concurrency approaching 25.
- Next infrastructure step: confirm the four-CPU backend allocation on a
  production-equivalent host, then add a second independently scraped backend
  replica before widening beyond the initial bound.

## Remaining risks and gates

- Local free disk is approximately 28 GiB after cache-only cleanup, below the
  preferred 30-40 GiB working headroom. No image, container, or volume was
  removed to recover more space.
- Production host CPU, RAM, and disk parity remain an operational verification
  gate; production deployment is still paused.
- Auth 25 and mixed 50 are known latency ceilings for the current single-process
  configuration, not launch blockers for the bounded target.
- A longer production-equivalent soak is non-blocking follow-up work after the
  initial canary.

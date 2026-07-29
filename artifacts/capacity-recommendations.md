# Capacity recommendations

Date: 2026-07-29

The single-backend local candidate sustains the tested 5-VU normal profile and a
gradual ramp to 20 VUs within the 1-second p95 and 2-second p99 SLOs, but an
abrupt jump to 20 VUs drives p99 to 3.43 seconds. This is a bounded host result,
not a universal concurrent-user rating.

## Initial operating envelope

- Launch a single-host pilot at no more than 10 concurrently active request
  producers until production telemetry confirms equivalent behavior. Preserve
  rate limits and use client jitter/backoff for retries and polling.
- Alert at p95 >500 ms for 10 minutes or p99 >1 second for 5 minutes; shed or
  queue nonessential expensive work before p99 reaches 2 seconds.
- Keep at least 40% backend CPU and 50% memory headroom. Scale out the stateless
  API before sustained backend CPU reaches 70%, connection pool waits appear,
  or p95 exceeds 500 ms.
- Treat RAG search as an expensive mutation-limited operation. Keep the current
  30/user/minute ceiling, cache repeat questions where authorization permits,
  and capacity-test a dedicated retrieval profile before raising it.
- Keep AI training, ingestion, email, and billing callbacks on worker queues.
  Alert on oldest-message age and queue depth; do not infer capacity from a
  zero-depth idle sample.

## Required production follow-up

Enable `pg_stat_statements` (with a reviewed retention/reset procedure),
database pool wait metrics, and endpoint-tagged latency dashboards. Repeat
normal, burst, and at least 30-minute soak tests on production-equivalent CPU,
memory, network, TLS, and managed database/Redis services. Add horizontal API
replicas and load-balancer health draining before accepting burst traffic at or
above the observed 20-VU spike.

No N+1 query, connection exhaustion, Redis pressure, queue starvation, memory
growth, restart, 5xx, or error-log signature was reproduced in the passing
profiles. The burst p99 failure is therefore handled as a scaling/traffic-shape
constraint, not attributed to an unproven source-code defect.

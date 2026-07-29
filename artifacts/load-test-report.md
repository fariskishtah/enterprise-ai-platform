# Load-test report

Date: 2026-07-29

Host: macOS ARM64, 8 logical CPUs, 8 GiB RAM

Classification: **normal/stress/soak pass; abrupt 20-VU spike exceeds p99 SLO**

## Scope and isolation

k6 2.1.0 exercised health, login, executive dashboard, machines, operational
alerts, document metadata, one bounded RAG retrieval per profile, one bounded
feedback submission per profile, billing plans, subscription status, usage
status, and payment history. The target was a newly rebuilt, seeded,
staging-like local Compose stack.

Runtime inspection proved `EMAIL_PROVIDER=disabled`,
`PAYMENT_PROVIDER=disabled`, `PAYMENT_SANDBOX_MODE=false`, and
`BILLING_ENTITLEMENTS_ENFORCED=false`. RAG used the repository's deterministic
local implementation. No paid AI, email, or payment provider was invoked.

## Results

| Profile | VUs | Requests | RPS | Mean | Median | p90 | p95 | p99 | Errors | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Smoke, 10 s | 1 | 98 | 7.90 | 33.95 ms | 6.95 ms | 45.29 ms | 83.81 ms | 870.53 ms | 0% | PASS |
| Normal, 50 s | 5 | 1,428 | 25.64 | 46.41 ms | 20.43 ms | 96.19 ms | 156.04 ms | 265.55 ms | 0% | PASS |
| Stress ramp, 40 s | 20 | 2,038 | 48.00 | 91.64 ms | 17.37 ms | 264.48 ms | 382.00 ms | 886.07 ms | 0% | PASS |
| Spike, 18 s | 20 | 788 | 38.08 | 304.14 ms | 184.63 ms | 662.43 ms | 949.03 ms | 3,430.82 ms | 0% | **FAIL p99** |
| Soak, 120 s | 3 | 2,588 | 21.15 | 40.09 ms | 16.35 ms | 88.92 ms | 150.19 ms | 236.02 ms | 0% | PASS |

The final evidence contains 6,940 requests, 6,950 successful checks, and zero
failed requests. The spike failed the explicit p99 <2,000 ms threshold and had
two iterations interrupted during rapid ramp-down. The failure is retained as
the demonstrated burst-capacity boundary.

An earlier diagnostic mixed RAG search into every iteration and received 104
HTTP 429 responses after reaching the intentional 30-requests/60-seconds
mutation limit. The final scenarios issue one RAG acceptance request each and
load only read paths. Those diagnostic 429s prove throttling but are not counted
as server failures or included in the final profile totals.

## Runtime observations

Across 37 five-second samples, peak backend use was 51.35% CPU and 415.8 MiB;
PostgreSQL 16.42% and 45.48 MiB; worker 11.89% and 234.4 MiB; Redis 2.08% and
9.65 MiB. Proxy/frontend peaks were below 2.5% CPU and 9 MiB.

No container restarted during the measured profiles (PostgreSQL's historical
restart counter was 25 both before and after). After the run PostgreSQL used 12
of 100 connections, one was active, and none had been active over one second.
Redis used 1.77 MiB with 21 clients, no blocked clients, and all application
queue depths were zero. Final profile logs contained no 5xx or ERROR-level
events. `pg_stat_statements` is not enabled in this disposable stack, so
historical slow-query attribution is a remaining observability gap.

Raw k6 exports were not retained because k6 includes setup data (access tokens)
in its summary JSON. This committed report and the redacted aggregate
`load-test-results.json` contain no credentials or tokens.

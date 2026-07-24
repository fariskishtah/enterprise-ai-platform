# Bounded load and soak report

The repository uses only k6 (`grafana/k6:2.1.0`). `scripts/run-load-tests.sh`
forwards explicitly supplied test credentials and bounded profile controls into
the container without printing them.

Profiles:

- smoke: health, metrics, and authenticated factory reads;
- API/demo: configurable 5 or 20 users with bounded dashboard reads;
- stress: up to 50 users with stop thresholds;
- training: one to three tiny deterministic jobs, one worker-facing queue;
- soak: up to 10 users for up to 30 minutes.

All targets default to local. A remote target requires the explicit
`ALLOW_REMOTE_TARGET=true` safeguard in the k6 code. Test data, results, and raw
logs remain under ignored paths.

## Observed controlled-staging results

Observed on 2026-07-24 on the disposable Compose staging stack. These figures
describe this single developer-laptop run, not production capacity.

| Profile | Bounded workload | p50 | p95 | p99 | Error rate | Throughput/result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Smoke | 5 users, 30 s, health + factory read | 19.05 ms | 162.65 ms | 196.34 ms | 0% | 9.00 req/s; 282 requests |
| Normal | 20 users, 25 s, health + factory read | 8.64 ms | 125.79 ms | 8.03 s | 0% | 33.11 req/s; 892 requests |
| Stress | ramp to 50 users, 40 s, health + dataset read | 64.72 ms | 513.46 ms | 4.40 s | 0% | 98.42 req/s; 4,062 requests |
| Import | 3 concurrent 10-row CSV uploads + exact replays | 112.42 ms | 886.41 ms | 1.17 s | 0% | all created; replay IDs matched |
| Reporting | 3 concurrent PDF/XLSX creates + downloads | 168.70 ms | 904.04 ms | 1.17 s | 0% | create p95 282.66 ms; download p95 65.56 ms |
| Training queue | 3 serial tiny three-tree jobs | 80.00 ms HTTP | 1.22 s HTTP | 1.63 s HTTP | 0% | all succeeded in 6.7 s total |
| Soak | 5 authenticated users, 30 min, health + dataset reads | 22.88 ms | 178.56 ms | 486.03 ms | 0% | 16,031 requests; 8,008 iterations |

At the 50-user sample, backend memory was 314 MiB of its 1 GiB limit and
sampled CPU was 49.5%; PostgreSQL used 51.3 MiB and the worker used 192.1 MiB.
There were no observed container restarts, 5xx responses, database saturation,
runaway queue, or stop-condition events. The normal profile's 8.03-second p99
outlier is a limitation despite its passing p95 gate and must be re-measured on
the intended hosting environment.

An initial 30-minute, five-user soak completed 8,120 iterations but correctly
failed its error threshold after the shared access token expired at 15 minutes:
4,610 protected dataset reads returned 401 while health checks remained
available. This identified a load-client session-lifecycle defect rather than
a service-capacity result. The soak client now gives each virtual user an
independent session and rotates its refresh token after an expected 401 before
retrying the protected read. The unchanged repeat passed all 16,046 checks,
including five successful audited token rotations, with no interrupted
iterations or container restarts. Authentication failure now aborts the profile
instead of allowing an unauthenticated health-only workload to satisfy the
thresholds.

No capacity claim is inferred from functional tests or synthetic data
generation.

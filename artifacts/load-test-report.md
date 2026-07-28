# Load-test report

Date: 2026-07-28  
Host: macOS ARM64, 8 logical CPUs, 8 GiB RAM

No new k6 load run was executed: `k6` is not installed on this host. Existing
scripts under `performance/k6/` and older reports are historical evidence and
were not relabelled as current results. The runtime health probe returned HTTP
200, but a probe is not a load test.

Install a pinned k6 release, start an isolated seeded staging stack, and run
`scripts/run-load-tests.sh` with disposable credentials. External AI, email, and
payment adapters must use explicit local/capture/sandbox modes. Record container
CPU/memory/restarts, PostgreSQL connections, Redis metrics, and worker queue depth
alongside request latency/error output. Production readiness remains blocked on
current smoke, normal, stress, spike, and bounded soak evidence.

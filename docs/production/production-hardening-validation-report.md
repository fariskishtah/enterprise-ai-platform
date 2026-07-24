# Production hardening validation report

Observed on 2026-07-24 from branch `production-hardening`. This report does not
claim DNS, TLS, provider delivery, or public-host behavior that was not exercised.

## Final unified result

```bash
eval "$(fnm env --shell zsh)"
fnm use 22
./scripts/validate-release.sh --full --allow-dirty
```

Exit code: **0**.

| Gate | Observed result |
| --- | --- |
| Repository, release docs, shell, and Python syntax | Passed; three open exception expiry dates checked |
| Backend static checks | Ruff, Black, mypy, and dependency consistency passed |
| Frontend static/build | ESLint, Prettier, TypeScript, Vite production build, and performance budgets passed |
| Backend tests | 811 passed, 3 skipped in 118.47 s |
| Mock browser/accessibility | 42 passed, 23 intentional real-backend skips |
| Dependency/source security | Production lock audit, registered development audit policy, Bandit, Gitleaks, Semgrep, Trivy filesystem, and license inventories completed |
| Candidate images | Backend, frontend, and reverse-proxy builds, SBOMs, actionable Trivy scans, and Nginx syntax passed |
| Seed | First pass created the bounded fixture; second pass reused it with zero duplicate domain, reading, dataset, model, prediction, or operational records |
| Smoke | Health, readiness, docs policy, login, current user, hierarchy read, and logout passed; prediction was the documented explicit opt-in skip |
| Backup/restore | Encrypted local backup, manifest checksums, and disposable restore passed |
| Real-backend browser | 23 of 23 passed |
| Cleanup | Validation-owned containers, networks, state, and disposable volumes were removed |

Migration `0021_add_support_requests` upgraded from `0020`, downgraded back to
`0020`, re-upgraded to `0021`, and produced no pending Alembic operations in the
focused migration validation. The final unified run confirmed `0021` as head.

## Additional observed evidence

- Support persistence, tenant scope, safe rendering, idempotency, bounded retry,
  failure state, and audit behavior passed five focused tests. Real Resend
  delivery was not attempted because no verified domain or provider key was
  available.
- The A4 vector PDF and typed XLSX/CSV paths passed focused extraction and
  rendering checks. A representative PDF rendered to a non-blank PNG.
- Deterministic 1,000-, 50,000-, and 250,000-row files generated in 0.04 s,
  0.12 s, and 0.85 s with an observed peak process footprint of about 9.7 MB.
- Smoke, normal, stress, import, reporting, training, and a 30-minute
  five-user authenticated soak completed with 0% request failures in their
  corrected runs. The soak issued 16,031 requests at p50 22.88 ms, p95
  178.56 ms, and p99 486.03 ms.
- Backend, frontend, and Redis restart probes recovered in 16 s, 1 s, and
  immediately, respectively. A stranded broker delivery was reproduced,
  reconciled to `succeeded`, and protected by atomic-claim focused tests.

## Active exceptions and blockers

- `SEC-2026-001`: development-only Black advisories; expires 2026-08-31.
- `SEC-2026-002`: unfixed findings in the official Python base image; expires
  2026-08-06.
- `SEC-2026-003`: React Router RSC-only advisory in a static SPA; expires
  2026-08-15. Unfiltered audit evidence is retained and every unrelated
  HIGH/CRITICAL finding remains blocking.
- Real DNS, public TLS, and public-host smoke were not available.
- Resend domain verification, SPF/DKIM/DMARC, and a real support delivery were
  not observed.
- Password-reset email remains unconnected, and application dataset/model/report
  objects remain on mounted local storage rather than an application S3 adapter.
- The normal load profile had an 8.03 s p99 outlier despite passing its p95 and
  error thresholds; intended-hosting capacity remains unmeasured.

## Recommendation

**Not ready** for public demo staging until real DNS/TLS and a real support-email
delivery are verified and the three security exceptions are accepted by their
owners. The validated code and local staging runtime are suitable for continued
internal staging review; no unrestricted production claim is made.

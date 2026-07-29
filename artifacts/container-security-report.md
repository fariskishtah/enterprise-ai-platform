# Container security report

Date: 2026-07-29  
Result: **actionable HIGH/CRITICAL scan PASS; unfixed backend risk accepted temporarily**

Three release targets were rebuilt from current source and scanned with Trivy
0.70.0 for vulnerabilities, secrets, and misconfiguration.

| Candidate | User | All HIGH/CRITICAL | With vendor fix | Actionable scan |
| --- | --- | ---: | ---: | ---: |
| backend | `10001:10001` | 23 occurrences / 12 CVEs | 0 | 0 |
| frontend | `101:101` | 0 | 0 | 0 |
| reverse proxy | `101:101` | 0 | 0 | 0 |

The backend findings are unfixed Debian 13 base-package advisories already
enumerated in `SEC-2026-002`, which expires 2026-08-06. The unfiltered scan was
retained; `--ignore-unfixed` was used only for the second blocking/actionable
pass. Application Python dependencies had no findings.

Dockerfile misconfiguration scanning found 0 HIGH/CRITICAL issues. Static and
rendered Compose review confirms non-root application/proxy users, `cap_drop:
ALL`, `no-new-privileges`, read-only root filesystems, bounded tmpfs mounts,
private application/data networks, reverse-proxy-only publishing, healthchecks,
restart policies, log rotation, and CPU/memory reservations and limits. Secrets
are injected at runtime; they are not image build arguments. The backend image
itself has no Dockerfile `HEALTHCHECK`, but production Compose supplies the
trusted-host readiness check.

Frontend and proxy use Alpine and run `apk upgrade --no-cache` before the final
image. The Python image cannot move to Alpine safely without a reviewed native
runtime change because the current Polars wheel is incompatible; base refresh
and rescan remain mandatory when Debian publishes fixes.

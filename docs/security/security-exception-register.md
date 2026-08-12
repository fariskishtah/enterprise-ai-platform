# Security exception register

This register is the only accepted location for temporary security-check exceptions.
An exception does not make a finding safe; it records ownership, scope, compensating
controls, and a mandatory review condition. Expired exceptions fail the release gate.

## Open exceptions

### SEC-2026-002 — Unfixed official Python base-image findings

| Field | Value |
| --- | --- |
| Advisories | `CVE-2025-69720`, `CVE-2026-8376`, `CVE-2026-9538`, `CVE-2026-13221`, `CVE-2026-41992`, `CVE-2026-42496`, `CVE-2026-42497`, `CVE-2026-48962`, `CVE-2026-53615`, `CVE-2026-54369`, `CVE-2026-57432`, `CVE-2026-57433` |
| Affected component | OS packages in the official `python:3.12-slim` runtime base |
| Fixed versions | None published in the scanned Debian repositories on 2026-07-23 |
| Scope | Backend and worker candidate image OS packages only |
| Risk assessment | High/critical vendor ratings require prompt base refresh. The application is non-root, capability-dropped, read-only in production, and does not invoke the affected command-line utilities; exposure is reduced but not eliminated. |
| Reason | Trivy reports 23 package findings with no available fixed package. Switching to Alpine was tested but `polars-runtime-32` has no compatible wheel and would require an unreviewed native toolchain/runtime migration. |
| Compensating controls | Full unfiltered image reports are retained; CI fails on every high/critical finding that has a fix. Runtime runs as UID 10001 with no added capabilities, no privilege escalation, read-only root filesystem, private data network, and reverse-proxy-only ingress. |
| Owner | Release engineering and security owners |
| Recorded | 2026-07-23 |
| Renewed | 2026-08-12 |
| Approved revision | `af3f48f4247809bae45cb06957799bf883f6c68c` |
| Security Owner decision | APPROVED renewal through 2026-08-26 under the documented compensating controls. |
| Expires | 2026-08-26 |
| Removal condition | A fixed official Python 3.12 base or reviewed low-CVE compatible base becomes available; rebuild, rescan, and remove this exception. |

This exception does not hide the findings: the unfiltered Trivy report remains a release
artifact. `--ignore-unfixed` is used only by the blocking second pass so newly actionable
high/critical findings fail immediately.

## Closed exceptions

### SEC-2026-001 — Closed 2026-08-12

Black was upgraded to `26.5.1`, its formatting/equivalence checks now pass, the two
`pip-audit` ignores were removed from CI and release validation, and the unfiltered
development-environment audit reports no known vulnerabilities.

### SEC-2026-003 — Closed 2026-08-12

React Router and React Router DOM were upgraded to `7.18.2`. The unfiltered npm audit
reports zero vulnerabilities, the narrow Trivy ignore was removed, and browser/build
validation is required by the normal release gate.

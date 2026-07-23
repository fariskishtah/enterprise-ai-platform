# Security exception register

This register is the only accepted location for temporary security-check exceptions.
An exception does not make a finding safe; it records ownership, scope, compensating
controls, and a mandatory review condition. Expired exceptions fail the release gate.

## Open exceptions

### SEC-2026-001 — Black formatter equivalence failure

| Field | Value |
| --- | --- |
| Advisories | `PYSEC-2026-2120`, `PYSEC-2026-2121` |
| Affected package | Development-only `black==24.10.0` |
| Fixed versions | `26.3.0` and `26.3.1`, respectively |
| Scope | Developer and CI formatting environment only; absent from production lock and images |
| Risk assessment | Low release-runtime exposure, but untrusted source files must not be formatted with this version |
| Reason | Black 26.5.1 produces a documented internal equivalence error on `app/ml/monitoring/capture.py` and would reformat 13 additional files. Adopting it without resolving that failure would make the required formatting gate unreliable. |
| Compensating controls | CI uses Black only against trusted checked-out repository source in check mode; Ruff, mypy, Bandit, Semgrep, tests, and production dependency/image scans remain mandatory. |
| Owner | Release engineering owner |
| Recorded | 2026-07-23 |
| Expires | 2026-08-31 |
| Removal condition | Resolve or isolate the formatter equivalence defect, reformat under a fixed Black release, and remove both CI audit ignores in the same reviewed change. |

No production dependency advisory is accepted by this exception. New findings require a
new reviewed entry; CI flags cannot be added without a matching, unexpired record.

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
| Expires | 2026-08-06 |
| Removal condition | A fixed official Python 3.12 base or reviewed low-CVE compatible base becomes available; rebuild, rescan, and remove this exception. |

This exception does not hide the findings: the unfiltered Trivy report remains a release
artifact. `--ignore-unfixed` is used only by the blocking second pass so newly actionable
high/critical findings fail immediately.

## Closed exceptions

None.

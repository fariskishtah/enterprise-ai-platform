# Dependency audit report

Date: 2026-07-29  
Result: **PASS with one documented frontend accepted risk**

## Backend

`pip-audit` checked all 93 dependencies resolved by
`backend/requirements/base.lock` and found 0 known vulnerabilities. A second
audit of the local development environment found 0 unignored vulnerabilities;
two Black formatter advisories remain explicitly ignored only for the
development-only package under `SEC-2026-001`. The production lock and runtime
image do not contain Black.

The lock is hash-pinned and candidate images install it with
`--require-hashes`. No production dependency was changed during this review.

## Frontend

`npm audit` inspected 259 dependency entries (10 production, 250 development,
34 optional; npm categories overlap) and reported 0 critical, 2 high, 0
moderate, and 0 low package findings. Both entries reduce to
`GHSA-qwww-vcr4-c8h2` through `react-router` and `react-router-dom` 7.18.1.

The vulnerable React Server Component action path is not deployed: this is a
static Vite SPA served by Nginx. The exact advisory/package scope is accepted
temporarily by `SEC-2026-003` through 2026-08-15. The fixed Router 8 line
requires a coordinated React/runtime migration; no unsafe major upgrade was
applied in this hardening pass. Every other HIGH/CRITICAL advisory remains a
blocking audit failure.

The final release build passed at 303,911 initial JavaScript bytes,
44,040 CSS bytes, and 347,958 total initial asset bytes. Bundle text
inspection found no credential markers. `VITE_API_BASE_URL` is the sole public
application build variable.

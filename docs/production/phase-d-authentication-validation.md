# Phase D authentication validation

Observed on 2026-07-28 from `feature/production-saas-upgrade`.

## Implemented contract

- Login and refresh JSON expose only the short-lived access token.
- The browser stores access state in module memory only and bootstraps a reload by
  rotating the HttpOnly refresh cookie.
- Refresh cookies have explicit Path, Max-Age, SameSite, configurable Domain, and
  production-required Secure attributes. Logout and unusable sessions expire both
  authentication cookies.
- Refresh/logout validate a readable double-submit CSRF cookie/header pair and reject
  browser Origins outside the exact CORS allowlist.
- Rotation persists family and parent lineage. Reuse of a rotated credential revokes
  every active descendant in that family under a locked database read.
- Existing session listing, individual revocation, revoke-other-sessions, password
  lifecycle revocation, and user deactivation remain enforced.

## Evidence

| Gate | Result |
| --- | --- |
| Backend suite | 862 passed, 3 skipped; 1,662 third-party warnings |
| Frontend static/build | ESLint, Prettier, TypeScript, and Vite build passed |
| Browser suite | 47 passed, 23 intentional real-backend skips (2 workers) |
| Focused typing | Cookie/auth routes, services, and repositories passed mypy |
| Compose | Local and placeholder production merged configurations resolved |
| Migration | PostgreSQL upgraded to `0028_add_refresh_token_families (head)` |
| Runtime | Rebuilt backend/frontend/worker; health and plan catalogue returned 200 |
| Packaged contract | OpenAPI has no refresh request body or JSON `refresh_token` property |

Focused tests cover login cookie creation and attributes, refresh rotation, ancestor
replay and descendant revocation, expiry, explicit session revocation, logout cookie
removal, CSRF mismatch/missing behavior, disallowed and allowed Origins, production
cookie flags, storage absence, reload bootstrap, refresh de-duplication, and logout
during an in-flight refresh.

The skipped browser cases require explicitly configured real-backend/staging accounts;
the skipped backend cases require opt-in direct integration variables. No Paymob claim
is included in this phase.

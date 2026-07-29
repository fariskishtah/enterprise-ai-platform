# Phase H billing frontend validation

Date: 2026-07-29
Branch: `feature/production-saas-upgrade`

## Delivered experience

- Public, backend-catalogue pricing with loading, retry, and authenticated actions.
- Owner/Admin billing workspace with lifecycle warnings, subscription details,
  usage thresholds, plan comparison, payment and invoice history, billing audit
  activity, and provider-event inspection.
- Accessible Paymob-hosted checkout contact form with a synchronous duplicate
  submission guard and stable idempotency key.
- Server-authoritative return screen for pending, succeeded, failed, cancelled,
  refunded, and reversed payments. Redirect success flags are ignored.
- Period-end cancellation confirmation, reactivation, upgrade, downgrade,
  expired/suspended recovery guidance, permission gating, dark-theme token usage,
  and responsive table containment.

## Automated evidence

- ESLint: passed.
- Prettier: passed.
- TypeScript and Vite production build: passed.
- Focused Playwright: 14 passed.
- Full Playwright regression: 61 passed, 23 explicitly gated real-backend skips.
- The focused suite asserts no unexpected browser console/page errors and no
  unmatched API requests in the primary billing workspace.
- Desktop 1280px and mobile 390px layouts were rendered in the actual Vite app
  against deterministic, non-sensitive API fixtures.

## Screenshot evidence

Fifteen `phase-h-*.png` files under `artifacts/screenshots/` cover current
subscription, usage, history, checkout, success, failure, cancellation, both plan
change directions, cancellation confirmation, past-due, suspended, admin, and
mobile states.

These browser fixtures validate UI behavior; they are not evidence of a real
Paymob sandbox transaction. Sandbox/live payment proof remains blocked by absent
deployment-owned credentials.

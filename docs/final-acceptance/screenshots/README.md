# Final acceptance screenshot evidence

Prepared on 2026-08-12 for the FactoryMind production handoff audit.

## Provenance and limitations

- `auth-*` images are copied from the repository's previously verified authentication acceptance evidence.
- `product-*` images are curated from the repository's verified UI evidence package. They use synthetic/demo data and contain no production credentials or customer data.
- `mobile-*` images are copied from previously verified responsive acceptance evidence.
- These are not fresh live-browser captures from the closure session: the Codex in-app browser had no browser runtime available. Live HTTPS, headers, redirects, TLS, health, deployment identity, migration, payment-provider state, and container health were instead rechecked using read-only HTTP and SSH commands.
- The blank `01_command_center.png` source was intentionally excluded; `product-command-center.png` uses the complete closing dashboard evidence instead.
- Screenshots demonstrate rendered states, not independent proof of backend authorization, tenant isolation, or cross-browser behavior. Those controls are covered by automated test and code evidence in the handoff.

## Contents

- Authentication: login, signup, verification, and mobile login.
- Core workflow: Command Center, factory hierarchy, onboarding, data quality, datasets, Guided AI, AutoML, training, models, evaluation, and prediction.
- Knowledge and operations: Knowledge Base, grounded RAG, refusal, monitoring, executive dashboard, reports, audit log, users/roles, settings, and billing.
- Responsive billing evidence.

No passwords, tokens, secret URLs, private credentials, or customer records are included.

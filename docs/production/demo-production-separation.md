# Demo and production separation

The deterministic simulator and seed remain available only for explicitly
enabled local or reviewed staging environments.

## Authoritative controls

- `DEMO_TOOLS_ENABLED` defaults to `false`.
- `APP_ENV=production` and the established `ENVIRONMENT=production` alias both
  select production safeguards.
- Production settings reject `DEMO_TOOLS_ENABLED=true`.
- Demo API dependencies also reject production independently of frontend state.
- Production Compose sets `APP_ENV=production`,
  `ENVIRONMENT=production`, and `DEMO_TOOLS_ENABLED=false` for the backend and
  worker.
- `scripts/seed_demo.py` exits before any API or database action in production.
- Frontend feature discovery fails closed and omits demo navigation when the
  backend reports the feature disabled.

Production deployment runs migrations only. It does not run demo or staging
seed scripts and does not create users, companies, factories, or credentials.

## Controlled staging

To enable the simulator in a disposable or reviewed staging environment:

```dotenv
APP_ENV=staging
DEMO_TOOLS_ENABLED=true
```

Use only the staging seed workflow with locally supplied credentials. Demo
records remain tagged and reset removes only the exact generated-resource
ledger. Never reuse these settings or credentials for production.

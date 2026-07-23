# Local reviewer demo

This repeatable local demo creates a small manufacturing hierarchy, realistic
sensor history, one tiny model, one exact-version prediction, and its monitoring
audit. AWS and other external services are not required.

## Prerequisites and startup

Docker with Compose is required. Create your ordinary local `.env` from
`.env.example`, then start only the services used by this workflow and apply
migrations:

```bash
docker compose up -d postgres redis backend training-worker
docker compose exec backend alembic upgrade head
```

The seed script expects a healthy backend and a running training worker:

```bash
./scripts/seed-demo.sh
```

The local-only defaults are `demo@example.com` and
`LocalDemoPassword1!`. Override them without editing a file when desired:

```bash
DEMO_EMAIL=reviewer@example.com \
DEMO_PASSWORD='AnotherLocalPassword1!' \
./scripts/seed-demo.sh
```

These credentials are intentionally for an isolated developer laptop only. Do
not reuse or deploy them. The seed output never prints the password or access
tokens.

## Reviewer path

1. Open `http://localhost:5173` and review the development-only Demo workflow
   card.
2. Open `http://localhost:8000/docs` from that card.
3. Use `POST /auth/login` with the local demo credentials and copy only the
   returned access token into Swagger's **Authorize** dialog.
4. Open `GET /companies`, then follow the named Northstar company to the
   Alexandria factory, CNC machine, spindle-temperature sensor, and its twelve
   readings.
5. Open `GET /ai/training-jobs` to see the single succeeded demo job.
6. Open `GET /ai/models/{registered_model_name}/versions/{version_or_alias}`
   with `demo_random_forest_regression` and the version printed by the seed.
7. Open `GET /ai/monitoring/prediction-events` and filter by that model name to
   see the successful one-row prediction audit and correlation ID.

The first run normally takes a few seconds after images are built, with a hard
90-second training poll limit. It inserts twelve one-minute temperature readings,
trains three trees from four rows on one thread, evaluates on two rows, and makes
one prediction.

Re-running the command reuses the exact named hierarchy, fixed-timestamp
readings, idempotent training job, registered version, and correlated prediction
audit. It does not delete or reset unrelated data or Docker volumes. If an
earlier demo job has failed, the script reports that state instead of silently
creating another model. Resetting the demo is intentionally not automated.

Known limitations: the seed demonstrates the bounded manufacturing-to-prediction
path and does not create every dataset, AutoML, knowledge, or chat resource
available in the authenticated frontend. The seed utility directly grants its
registered local user the engineer role because the secure public API
intentionally has no role-elevation endpoint.

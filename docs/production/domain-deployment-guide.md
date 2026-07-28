# Real-domain deployment guide

This guide prepares a reviewed single-domain HTTPS deployment. It does not
authorize unrestricted production use.

## DNS, TLS, and runtime

1. Point the selected DNS A/AAAA record to the controlled server.
2. Restrict inbound traffic to SSH from the operator network and public 80/443.
3. Issue a certificate outside the application. HTTPS preparation stages only
   the active certificate for the unprivileged reverse proxy; the Certbot account
   tree remains host-only.
4. Create an untracked production environment from
   `docs/production/environment-template.md`.
5. Verify the exact host, origin, and public URLs match.
6. Run `./scripts/deploy-production.sh --env-file <file> --https`.

The generated Nginx configuration redirects HTTP to the exact HTTPS base URL,
accepts the configured `server_name`, exposes no internal service ports, forwards
the original host/protocol, applies HSTS and bounded request limits, and proxies
the browser API only under `/api`.

## Required preflight

- `APP_ENV=production`, API documentation off, demo tools off.
- Exact `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`; no wildcard or local origin.
- Independently generated database, JWT, backup, and Grafana secrets.
- Resend domain verified; SPF and DKIM published; DMARC monitored.
- Support test delivery observed without exposing the provider key.
- Login and mutation rate limits enabled.
- PostgreSQL and Redis not published.
- Encrypted backup schedule and a recent disposable restore result.
- Docker log rotation, disk monitoring, and object/model artifact growth alarms.
- Health, readiness, worker heartbeat, Prometheus, logs, and traces reviewed.

## Current limitations

Browser tokens use session storage and the API uses bearer authentication; the
application does not issue authentication cookies. `COOKIE_SECURE` and
`COOKIE_SAMESITE` are validated deployment intent, not evidence of an HttpOnly
cookie flow. Password-reset email delivery is not connected to Resend. Dataset,
model, and report objects use mounted local storage rather than an application
S3 adapter. These are blockers for an unrestricted production recommendation,
but not for a reviewed public demo with non-customer data and controlled access.

Do not expose seed credentials, run the demo seed, enable the simulator, or use
private customer data on the public-video environment.

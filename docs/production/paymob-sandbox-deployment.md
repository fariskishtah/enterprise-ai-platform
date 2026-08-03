# Isolated Paymob sandbox deployment

This runbook prepares the public sandbox at
`https://factorymind-sandbox.ddnsgeek.com`. It does not authorize live payments
or production data changes. Production must continue to satisfy
`PAYMENT_PROVIDER=disabled`.

## Hard boundaries

- Production Compose project: `ai-manufacturing-platform`.
- Sandbox Compose project: `factorymind-paymob-sandbox`.
- Never read, copy, source, or modify `.env.production` for this workflow.
- Never put Paymob values in shell arguments, Git, logs, screenshots, or reports.
- Never remove volumes during ordinary stop or rollback.
- Certificate issuance and shared-edge activation are separate manual actions.
- The browser return remains UX-only; only an authenticated provider callback can
  grant access.

Both public names currently resolve to the same host, so the existing Nginx edge
is the only listener on ports 80 and 443. The sandbox application and data plane
remain separate; the edge gains only a second virtual host and a connection to an
external network containing the sandbox reverse proxy.

## Files and resources

The sandbox overlay is `docker-compose.paymob-sandbox.yml`. Use it after the base,
production-hardening, and staging migration overlays. Always pass the explicit
project name; do not rely on the base Compose `name`.

Project-scoped PostgreSQL, Redis, artifact volumes, and private application/data
networks are created with the `factorymind-paymob-sandbox` prefix. Only the two
reverse proxies may join `factorymind-paymob-sandbox-edge`. Sandbox backend,
workers, PostgreSQL, and Redis never join that edge network and publish no host
ports.

The sandbox uses distinct queue names for billing callbacks, transactional email,
training, datasets, RAG, and monitoring even though its Redis container is already
physically separate.

## Production label discovery

Run on the real Docker host before any sandbox mutation:

```bash
docker ps --format 'table {{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}'
./scripts/paymob-sandbox.sh preflight
```

The script filters only:

```text
com.docker.compose.project=ai-manufacturing-platform
```

It does not assume production service names. It identifies roles from safe Docker
metadata:

- reverse proxy: mounted Nginx default/routes files and the Nginx listener port;
- backend: Uvicorn command and port 8000;
- PostgreSQL: data-directory mount and port 5432;
- Redis: data mount and port 6379.

Exactly one running container must match each role, each must carry a non-empty
`com.docker.compose.service` label, and the backend must pass a boolean check that
its payment provider is disabled. Values from the production environment are
never printed.

## Local dry run and secret configuration

The dry run does not contact Docker:

```bash
./scripts/paymob-sandbox.sh dry-run
```

After preflight is accepted, create the ignored mode-0600 sandbox environment:

```bash
umask 077
./scripts/paymob-sandbox.sh configure </dev/tty
```

The command generates database, application, and observability secrets locally.
Paymob sandbox values are read with terminal echo disabled and never appear in
arguments or output. An existing environment file is not replaced without:

```bash
./scripts/paymob-sandbox.sh configure \
  --confirm REPLACE-SANDBOX-ENV </dev/tty
```

`PAYMOB_API_KEY` and `PAYMOB_IFRAME_ID` are not used by the current Intention
adapter.

## Start, migrate, and seed

Starting the stack does not activate public ingress:

```bash
./scripts/paymob-sandbox.sh start --confirm START-SANDBOX
```

The action validates Compose, creates only the labeled sandbox edge network,
builds images, starts the sandbox PostgreSQL and Redis services, upgrades the
empty sandbox database to Alembic head, runs `alembic check`, and starts the
sandbox backend, worker, frontend, and internal reverse proxy.

Seed two verified Owners in separate disposable companies:

```bash
./scripts/paymob-sandbox.sh seed \
  --confirm SEED-SANDBOX-USERS </dev/tty
```

Passwords and email addresses are one-shot process values. They are not retained
in `.env.paymob-sandbox` and are not printed. No platform operator, payment, or
successful subscription is seeded.

## Paymob dashboard contract

Use test mode and the intended Egypt card integration only.

- Transaction Processed Callback:
  `https://factorymind-sandbox.ddnsgeek.com/api/billing/webhooks/paymob`
- Transaction Response Callback fallback:
  `https://factorymind-sandbox.ddnsgeek.com/settings/billing/return`

The Intention API sends the processed callback in `notification_url` and a
per-payment browser return with opaque `state` in `redirection_url`. Do not add a
fixed HMAC query value. Integration ID, merchant owner ID, environment, source,
amount, and currency must match the local payment contract.

## Certificate and ingress approval gates

Certificate issuance uses the ACME webroot already mounted into the discovered
production proxy. It creates a separate certificate and does not expand or
replace the production certificate:

```bash
./scripts/paymob-sandbox.sh issue-certificate \
  --confirm ISSUE-SANDBOX-CERTIFICATE
```

The certificate is initially staged only under
`.deployment/paymob-sandbox/https/certs`.

Public activation is a separate command:

```bash
./scripts/paymob-sandbox.sh activate-ingress \
  --confirm ACTIVATE-SANDBOX-INGRESS
```

Activation performs a fresh read-only production preflight, discovers the live
Nginx config and certificate mounts, preserves a byte-for-byte config backup,
copies the sandbox certificate beside the production pair, connects only the
production proxy to the controlled edge network, renders the dual-host template,
runs `nginx -t`, and reloads only Nginx. Any validation error restores the backup.
Production backend, worker, PostgreSQL, Redis, certificate paths, and routes are
not restarted or replaced.

After a successful Certbot renewal, restaging and Nginx reload remain explicit:

```bash
./scripts/paymob-sandbox.sh refresh-certificate \
  --confirm REFRESH-SANDBOX-CERTIFICATE
```

## Verification

```bash
./scripts/paymob-sandbox.sh verify-isolation
```

The verifier confirms:

- production provider remains disabled;
- sandbox provider is Paymob in staging sandbox mode;
- production and sandbox PostgreSQL data mounts differ;
- sandbox backend, PostgreSQL, and Redis publish no host ports;
- production health remains available;
- when ingress is active, sandbox health works and `/api/metrics` remains hidden.

## Rollback and teardown

Restore production Nginx and disconnect the production proxy before stopping the
sandbox:

```bash
./scripts/paymob-sandbox.sh deactivate-ingress \
  --confirm DEACTIVATE-SANDBOX-INGRESS

./scripts/paymob-sandbox.sh stop --confirm STOP-SANDBOX
```

Stop removes only sandbox containers. Networks, database, Redis state, queued
callbacks, reconciliation evidence, and every named volume remain retained.

Volume removal is a separate exceptional action:

```bash
./scripts/paymob-sandbox.sh purge-volumes \
  --confirm DELETE-SANDBOX-VOLUMES
```

It refuses to proceed while sandbox containers or ingress exist and selects only
volumes carrying both the sandbox Compose project label and the FactoryMind
sandbox ownership label. Production-labeled, unlabeled, wildcard, or unresolved
volumes are rejected.

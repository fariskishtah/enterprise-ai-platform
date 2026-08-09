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

`PAYMOB_EXPECTED_CALLBACK_OWNER` is the expected HMAC-authenticated Transaction
Processed Callback `obj.owner` value. It is not assumed to be the Dashboard MID.
`PAYMOB_MERCHANT_ID` is a deprecated fallback; the canonical key takes precedence
when both exist.

For an existing Sandbox that already has at least two distinct, terminal
`quarantined_wrong_merchant` captured-success callbacks, the owner can be staged
from persisted card-free evidence without displaying it:

```bash
./scripts/paymob-sandbox.sh bootstrap-owner \
  --confirm BOOTSTRAP-SANDBOX-CALLBACK-OWNER
```

The command verifies the Sandbox database identity, runtime mode, callback and
payment integration/environment/amount/currency bindings, identical numeric
owners, and at least two distinct events. It updates only
`PAYMOB_EXPECTED_CALLBACK_OWNER` in `.env.paymob-sandbox`, preserves mode `0600`,
does not run `configure`, and never changes or replays webhook or payment rows.

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
fixed HMAC query value. Integration ID, expected callback `obj.owner`,
environment, source, amount, and currency must match the local payment contract.

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

The approved production HTTPS overlay pre-provisions two read-only mounts:
`/etc/nginx/sandbox-conf.d` for independently managed virtual hosts and
`/etc/nginx/paymob-sandbox-certs` for the separate Sandbox certificate. The
production `default.conf` contains only a wildcard include for the first mount;
activation refuses unknown or older layouts.

Activation performs a fresh read-only production preflight, validates those
mounts, connects only the production proxy to the controlled edge network,
atomically installs `paymob-sandbox.conf`, runs `nginx -t`, and reloads only
Nginx. It never rewrites or backs up the production `default.conf`. On failure it
removes only the new Sandbox include, reloads the prior active configuration,
and disconnects an edge membership created by that attempt. Repeated activation
is a no-op only when the marker, include content, certificate mount, and edge
membership all match.

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
- production and sandbox PostgreSQL and Redis data mounts differ;
- database names, users, passwords, backend database URLs, Redis URLs, signing
  keys, and every queue namespace differ without printing their values;
- production and Sandbox data-plane containers share no Docker network IDs;
- only the two reverse proxies may join the controlled edge network;
- the production proxy is the sole owner of host ports 80 and 443;
- sandbox backend, reverse proxy, PostgreSQL, and Redis publish no host ports;
- production health remains available;
- when ingress is active, sandbox health works and `/api/metrics` remains hidden.

## Rollback and teardown

Remove only the managed Sandbox include and disconnect the production proxy
before stopping the Sandbox:

```bash
./scripts/paymob-sandbox.sh deactivate-ingress \
  --confirm DEACTIVATE-SANDBOX-INGRESS

./scripts/paymob-sandbox.sh stop --confirm STOP-SANDBOX
```

Deactivation validates and reloads Nginx after removing the include and restores
that include if validation or reload fails. It never replaces production server
blocks or production certificates. Stop removes only Sandbox containers.
Networks, database, Redis state, queued callbacks, reconciliation evidence, and
every named volume remain retained.

Volume removal is a separate exceptional action:

```bash
./scripts/paymob-sandbox.sh purge-volumes \
  --confirm DELETE-SANDBOX-VOLUMES
```

It refuses to proceed while sandbox containers or ingress exist and selects only
volumes carrying both the sandbox Compose project label and the FactoryMind
sandbox ownership label. Production-labeled, unlabeled, wildcard, or unresolved
volumes are rejected.

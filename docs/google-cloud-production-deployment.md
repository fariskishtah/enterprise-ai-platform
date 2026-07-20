# Google Cloud single-VM production deployment

This runbook prepares the platform for an initial Docker Compose deployment on
one Google Cloud Compute Engine VM. It does not provision cloud resources and it
is not a high-availability design. PostgreSQL, Redis, application artifacts, and
observability history remain on that VM's Docker volumes.

## Architecture and sizing

Use an Ubuntu LTS VM with approximately 4 vCPU and 8 GB RAM, such as a custom
machine shape. Start with a 50–100 GB balanced persistent boot disk and increase
it for retained model artifacts, database growth, and the optional observability
profile. Monitor free bytes and inodes; disk exhaustion can stop PostgreSQL and
the telemetry stores.

The core profile runs the public Nginx reverse proxy, static frontend, backend,
one training worker, PostgreSQL, and Redis. Only Nginx publishes a host port.
Application, data, public, and observability networks isolate service paths;
PostgreSQL and Redis share only the internal data network with the backend and
worker. The `observability` profile adds the existing exporters, cAdvisor,
Alertmanager, Prometheus, Loki, Alloy, Tempo, and Grafana with conservative
single-VM limits. Leave it disabled until core resource use is measured.

Named volumes preserve PostgreSQL, Redis, MLflow, model artifacts, AI artifacts,
and telemetry across container replacement. They are not backups and do not
survive loss of the VM and its disk.

## Manual Google Cloud setup

1. Create the Ubuntu VM and reserve a static external IPv4 address. Attach the
   address to the VM before creating DNS records.
2. Configure firewall ingress for only:
   - TCP 22 from a narrow administrator source range, not the whole internet.
   - TCP 80 from intended web clients for HTTP and certificate challenges.
   - TCP 443 from intended web clients when HTTPS is enabled.
   Do not allow backend, database, Redis, Grafana, Prometheus, Loki, Tempo,
   Alertmanager, Alloy, exporter, or Docker daemon ports.
3. Enable automatic Ubuntu security updates and install Docker Engine from
   Docker's official Ubuntu repository together with the Compose plugin. Add the
   deployment operator to the `docker` group only if root-equivalent Docker
   access is acceptable. Verify:

   ```bash
   docker version
   docker compose version
   ```

4. Clone the repository, check out the reviewed deployment revision, and run all
   deployment commands from the repository root.

## Production environment file

Create an ignored file readable only by the deployment operator:

```bash
cp .env.example .env.production
chmod 600 .env.production
```

Replace every local or placeholder credential. At minimum set matching
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `DATABASE_URL`; an
internal `REDIS_URL`; a high-entropy `SECRET_KEY`; unique `JWT_ISSUER` and
`JWT_AUDIENCE`; an exact HTTPS `CORS_ALLOWED_ORIGINS`; and strong Grafana
credentials before enabling observability. Set `ENVIRONMENT`, `LOG_ENVIRONMENT`,
`OBSERVABILITY_ENVIRONMENT`, and `OTEL_ENVIRONMENT` to `production`. Keep
`TRUSTED_PROXY_IPS=*` only while the backend has no published port and accepts
traffic solely from the isolated application network.

Do not store `.env.production` in Git, an image, a VM startup script, shell
history, or deployment logs. Compose environment variables remain visible to
root-equivalent Docker operators, so restrict VM and Docker access.

## Deploy and verify

The deploy script validates the merged Compose model, pulls pinned service
images, builds the application images, starts PostgreSQL and Redis, runs Alembic
exactly once in a one-shot backend container, starts the core services, and runs
bounded health checks:

```bash
./scripts/deploy-production.sh --env-file .env.production
./scripts/verify-production.sh --env-file .env.production
```

The backend and worker never run migrations during ordinary startup, avoiding
replica races. Review every migration for backward compatibility before deploy;
the rollback script intentionally never runs an Alembic downgrade.

Enable the optional observability profile only after the core stack is stable:

```bash
docker compose --project-name ai-manufacturing-production \
  --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml \
  --profile observability up -d
```

Validate internal telemetry endpoints with `docker compose exec` rather than
publishing them. The existing Alertmanager configuration has no external paging
destination, so dashboards and alerts do not yet guarantee human notification.

## DNS and HTTPS

Create an `A` record for the intended hostname pointing to the reserved static
IP. Keep DNS TTL modest during the first cutover. The checked-in configuration
serves HTTP on port 80 so it can be verified without a domain.

Choose one HTTPS pattern before serving real credentials:

- **Nginx and Let's Encrypt:** obtain certificates outside the repository,
  mount the host certificate directory read-only at `/etc/letsencrypt`, enable a
  deployment-local copy of `infrastructure/nginx/https.conf.example`, and publish
  only Nginx port 443. Automate renewal on the host and validate Nginx before
  reload. Never commit private keys or certificates.
- **Cloudflare proxy:** place the hostname behind Cloudflare, use strict TLS from
  Cloudflare to the VM with an origin certificate mounted into Nginx, restrict
  origin ingress to the authorized proxy path where operationally practical,
  and retain end-to-end HTTPS. Do not use a mode that sends HTTP to the origin.

After HTTPS is active, redirect HTTP to HTTPS and enable HSTS only after every
required hostname works correctly over TLS.

## Backups

Schedule the existing PostgreSQL backup with the production Compose project and
environment, then monitor its exit status and run regular isolated restore
verification. A cron invocation can supply Compose's standard environment:

```cron
15 2 * * * cd /absolute/path/to/ai-manufacturing-platform && COMPOSE_PROJECT_NAME=ai-manufacturing-production COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml COMPOSE_ENV_FILES=.env.production BACKUP_DIR=/absolute/path/to/backups/postgres RETENTION_DAYS=7 ./scripts/backup-postgres.sh >>/absolute/path/to/logs/postgres-backup.log 2>&1
```

Copy backups off the VM using encrypted, access-controlled storage and verify
those copies. The local seven-day retention alone does not protect against VM,
disk, account, or regional loss. Follow the backup and disaster-recovery runbook
for restore drills; never restore over the live database during verification.

## Upgrade and rollback

Deploy only a reviewed Git revision. If an application rollback is needed,
supply the exact previously known-good revision:

```bash
./scripts/rollback-production.sh PREVIOUS_GIT_REVISION \
  --env-file .env.production
```

Rollback builds from a temporary detached Git worktree and reuses the fixed
Compose project and existing volumes. It does not reset the current checkout,
delete volumes, restore data, or downgrade the database. A revision incompatible
with already-applied migrations cannot be made safe by this script; roll forward
or use the separately authorized disaster-recovery process.

## Operations and billing safeguards

- Monitor `docker compose ps`, container health/restarts, host CPU, memory, disk,
  inode use, backup age, PostgreSQL/Redis health, queue depth, and the existing
  SLO dashboards. Keep OS and Docker patches current.
- Set Google Cloud Billing budgets and multiple threshold notifications before
  deployment. Budgets alert but do not cap spending, so also review billing
  reports and unexpected resource creation regularly.
- Label the VM, disks, snapshots, reserved IP, and any certificate-related
  resources with an owner and credit-expiry date.
- Before credits or the evaluation period expire, export required backups, stop
  the VM if temporary suspension is enough, or delete the VM and explicitly
  remove unneeded persistent disks, snapshots, and reserved external IPs. Verify
  the billing console afterward; deleting a VM alone may leave chargeable disks
  and addresses.

## Remaining limitations

This is a single-host deployment with brief upgrade interruptions, local
PostgreSQL/Redis/artifact storage, no automatic failover, no managed secret
store, no image registry promotion workflow, no automatic certificate issuance,
no external paging, and no tested production-scale capacity result. The optional
observability stack is best-effort on an 8 GB host. Move state off-host and add
measured recovery, security, and availability controls before treating the
platform as highly available production infrastructure.

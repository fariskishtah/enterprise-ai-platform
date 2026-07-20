# Optional production HTTPS

Production HTTPS is an explicit, optional overlay on the existing HTTP-only
deployment. Nginx terminates TLS on container port `8443`; host Certbot owns
certificate issuance and renewal under `/etc/letsencrypt`. Certificates, private
keys, generated Nginx configuration, and production environment files remain
outside Git.

## Prerequisites

- A production host prepared according to the main deployment runbook.
- DNS for the intended hostname resolving to the host.
- Host TCP ports 80 and 443 open to intended clients.
- Docker Engine and Compose, plus host Certbot.
- A valid Let's Encrypt certificate at
  `/etc/letsencrypt/live/$HTTPS_DOMAIN/fullchain.pem` and matching private key at
  `/etc/letsencrypt/live/$HTTPS_DOMAIN/privkey.pem`.

The environment file must include values matching the public origin:

```dotenv
HTTPS_DOMAIN=manufacturing.example.com
PUBLIC_BASE_URL=https://manufacturing.example.com
PUBLIC_HTTPS_PORT=443
CORS_ALLOWED_ORIGINS=["https://manufacturing.example.com"]
```

`HTTPS_DOMAIN` is a hostname only. `PUBLIC_BASE_URL` must be exactly
`https://$HTTPS_DOMAIN`, with `:$PUBLIC_HTTPS_PORT` only when the public port is
not 443. Keep `PUBLIC_HTTP_PORT=80` unless the deployment deliberately maps a
different host port.

## One-time certificate issuance

For a new host without a certificate, stop only the public proxy briefly so
Certbot's standalone listener can use port 80:

```bash
docker compose --project-name ai-manufacturing-production \
  --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml \
  stop reverse-proxy
sudo certbot certonly --standalone -d "$HTTPS_DOMAIN"
```

Do not copy certificate material into the repository. Deploy immediately after
issuance to restore the public service. Existing Certbot installations may keep
their current authenticator; the checked-in HTTPS template also preserves
`/.well-known/acme-challenge/` from the configured host webroot for webroot-based
renewal.

## Deploy and verify HTTPS

Preparation is normally invoked by deployment, but can be run independently and
repeated safely:

```bash
./scripts/prepare-production-https.sh --env-file .env.production
```

It validates the hostname, public URL, certificate files, and generated Nginx
configuration, then writes only `.deployment/https/default.conf`, which is
gitignored.

Deploy with the explicit flag:

```bash
./scripts/deploy-production.sh --env-file .env.production --https
```

Re-run bounded verification without redeploying:

```bash
./scripts/verify-production.sh --env-file .env.production --https
```

Verification checks service health and port isolation, HTTP health behavior,
the public TLS certificate and hostname through the local host address, HTTPS
`/healthz`, the frontend and `/api/health`, and the HSTS response header.

## Certbot renewal deploy hook

The repository helper validates and reloads only the running production reverse
proxy. It does not invoke Certbot or restart application/data services. Install a
small host hook that calls the script from the deployment checkout, replacing
the example absolute paths:

```bash
sudo sh -c 'cat > /etc/letsencrypt/renewal-hooks/deploy/reload-ai-platform-proxy' <<'HOOK'
#!/bin/sh
exec /absolute/path/to/ai-manufacturing-platform/scripts/reload-proxy-after-cert-renewal.sh \
  --env-file /absolute/path/to/ai-manufacturing-platform/.env.production
HOOK
sudo chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-ai-platform-proxy
```

Exercise Certbot's renewal path before relying on it:

```bash
sudo certbot renew --dry-run
```

The hook first runs `nginx -t` inside the active container. A failed validation
prevents reload and leaves the existing worker, backend, database, and proxy
processes untouched.

## Roll back to HTTP-only

Redeploy without `--https`:

```bash
./scripts/deploy-production.sh --env-file .env.production
./scripts/verify-production.sh --env-file .env.production
```

This restores the tracked HTTP-only proxy configuration and removes the 443
publication from the recreated proxy container. It does not delete certificates,
generated files, volumes, or unrelated data.

## Security notes and limitations

- Never commit `.env.production`, `.deployment/`, `/etc/letsencrypt`, certificate
  contents, or private keys.
- Keep `/etc/letsencrypt` mounted read-only and restrict host root/Docker access.
- TLS 1.2 and 1.3 are enabled; HSTS is returned only by the HTTPS server.
- HTTP redirects are enabled only when the HTTPS override replaces the default
  proxy configuration. `/healthz` and ACME challenges remain available on HTTP.
- The proxy reload helper assumes the fixed production Compose project name used
  by the deployment scripts.
- Certificate issuance and renewal depend on host Certbot and DNS/firewall
  correctness; the repository does not automate DNS or run Certbot.
- HTTP-only production deployment remains fully supported and requires neither a
  certificate nor internet access during verification.

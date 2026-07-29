# Production reverse proxy example

The supported example is the unprivileged Nginx service in
`docker-compose.prod.yml`. Plain HTTP is defined by
`infrastructure/nginx/reverse-proxy.conf`; TLS is generated from
`infrastructure/nginx/https.conf.template` so no customer hostname is stored in
source control.

Generate and validate a deployment-owned copy:

```bash
HTTPS_DOMAIN='<application-host>' \
PUBLIC_BASE_URL='https://<application-host>' \
./scripts/prepare-production-https.sh

docker compose --env-file <production-env-file> \
  -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```

The proxy is the only service that publishes a host port. `/api/` is routed to
the backend, all other paths to the static frontend, forwarding the original
host, scheme, request ID, and client chain. Upload limits and route-specific
timeouts are centralized in `infrastructure/nginx/routes.inc`. `/metrics` is
denied at the public edge; Prometheus reaches it only over the internal network.

Terminate TLS at only one trusted layer. When a managed load balancer
terminates TLS, keep the proxy private, restrict `TRUSTED_PROXY_IPS` to that
layer, and ensure it overwrites rather than appends untrusted forwarding
headers. When Nginx terminates TLS directly, mount the certificate and private
key read-only and expose the generated HTTPS port mapping described by the
deployment runbook. Never pass a client-supplied `X-Forwarded-Proto` through
unchanged.

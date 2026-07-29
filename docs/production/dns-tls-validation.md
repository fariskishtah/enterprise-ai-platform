# DNS and TLS production acceptance

Status on 2026-07-29: **configuration validated; public acceptance blocked**.
No deployment-owned domain, DNS zone, certificate, or internet-facing host was
available in this workspace. This document therefore does not claim that a
public hostname or certificate has been accepted.

## Required production values

Set these through the deployment secret/configuration store, never in Git:

- `APP_PUBLIC_URL=https://<application-host>`
- `API_BASE_URL=https://<application-host>/api` for the included same-origin proxy
- `ALLOWED_HOSTS=<application-host>` (comma-separated only when every entry is intentional)
- `CORS_ALLOWED_ORIGINS=https://<application-host>`
- `COOKIE_DOMAIN=<shared-parent-domain>` only if cross-subdomain cookies are required
- `COOKIE_SECURE=true`, `COOKIE_SAMESITE=lax`
- `PAYMOB_WEBHOOK_URL=https://<application-host>/api/billing/webhooks/paymob`
- email sender, reply-to, and provider settings from the email acceptance checklist

`APP_PUBLIC_URL` supplies verification, reset, invitation, and frontend return
links. `API_BASE_URL` supplies backend-facing links. Both must be checked in a
received test message and a real hosted-checkout return before approval.

## DNS and certificate checklist

1. Reserve the public address and create the intended A/AAAA records with a
   short migration TTL. Confirm authoritative and two independent recursive
   resolvers return only the intended addresses.
2. Permit public TCP 80 only for redirect/ACME and TCP 443 for application
   traffic. Do not expose application, database, Redis, or observability ports.
3. Issue a certificate for every configured hostname. Confirm the full chain,
   SANs, issuer, validity window, renewal timer, and a dry-run renewal.
4. Generate the TLS proxy configuration with
   `scripts/prepare-production-https.sh`; run `nginx -t` before reload.
5. Confirm HTTP redirects to HTTPS without changing the path/query. Confirm
   TLS 1.0/1.1 fail and TLS 1.2/1.3 succeed.
6. Confirm HSTS, CSP, frame, content-type, referrer, and permissions headers.
   Enable HSTS preload only after every affected subdomain is permanently HTTPS.
7. From outside the deployment network, check `/healthz`, `/api/health`, and
   `/api/ready`; confirm `/metrics` and OpenAPI are not public.

Suggested evidence commands (replace placeholders locally, do not commit their output):

```bash
dig +short A <application-host>
curl -fsSI http://<application-host>/healthz
curl -fsSI https://<application-host>/healthz
openssl s_client -connect <application-host>:443 -servername <application-host> -verify_return_error </dev/null
```

Approval requires the operator to record the deployment ID, hostname,
certificate fingerprint (not private key), DNS results, renewal test, and UTC
timestamp in the release evidence.

# Deployment validation report

Date: 2026-07-29  
Classification: **local configuration PASS; public DNS/TLS BLOCKED**

## Verified from the release candidate

- Production Compose exposes only the reverse proxy and requires core database,
  application, host, CORS, and Grafana secrets/configuration.
- Secure cookies, verification requirements, production logging, disabled API
  docs, restart policies, resource reservations/limits, log rotation, read-only
  application filesystems, dropped capabilities, and non-root users are encoded.
- Data and application networks are internal. PostgreSQL and Redis publish no
  host ports.
- Nginx supplies HTTP-to-HTTPS generation, TLS 1.2/1.3, HSTS and defensive
  headers, internal metrics denial, request forwarding, health endpoints, and
  upload/time-out limits.
- The backend healthcheck now derives its Host header from `ALLOWED_HOSTS`; no
  deployment-specific public domain remains embedded in Compose.

Automated command output and test counts are recorded by the final test report.

## Blocked live checks

No public domain, DNS control, certificate, deployed address, or production
environment file was available. Consequently authoritative DNS propagation,
external redirects, live certificate chain/SAN/renewal, public reachability,
firewall posture, and externally generated email/payment links remain operator
acceptance gates. Follow `docs/production/dns-tls-validation.md` and attach
redacted evidence before production approval.

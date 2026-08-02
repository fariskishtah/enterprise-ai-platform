# Transactional email

Transactional email is provider-agnostic and asynchronous. The API commits the
business record and an `outbound_email_messages` row before publishing only its
UUID to the existing Dramatiq worker. Provider outages therefore do not remove
the original support, account, invitation, or billing event.

Supported modes are:

- `capture`: local development capture. The durable row becomes `captured`, not
  `sent`, so local behavior never masquerades as external delivery.
- `resend`: HTTPS delivery through Resend.
- `smtp`: SMTP with optional STARTTLS and credentials.
- `disabled`: explicit no-delivery mode. Attempts fail safely.

The provider protocol is intentionally small enough to add SendGrid or Amazon
SES without changing callers. Every email has responsive, escaped HTML and a
plain-text fallback. The template catalogue covers email verification, password
reset, welcome, team invitation, feedback received, support request received,
subscription confirmation, payment confirmation, payment failure, and
subscription cancellation.

## Durable lifecycle

Rows move through `queued`, `processing`, `retrying`, then one of `captured`,
`sent`, or `failed`. Retries after the initial attempt are bounded by
`EMAIL_MAX_RETRIES`; retryable
transport, throttling, and 5xx failures use exponential backoff based on
`EMAIL_RETRY_BASE_SECONDS`. Permanent provider rejection fails immediately.
A unique business-event deduplication key prevents normal duplicate publishing.
Scheduled reconciliation republishes queued and due-retry rows and safely
recovers processing rows left stale by an interrupted worker.

Prometheus exposes `transactional_email_delivery_total` and
`transactional_email_delivery_duration_seconds` with bounded labels only.
Recipient addresses, subjects, bodies, tokens, provider responses, credentials,
and authorization headers are excluded from delivery logs and metric labels.

## Configuration

Use `.env.example` as the source of truth:

```dotenv
EMAIL_PROVIDER=capture
EMAIL_FROM_ADDRESS=support@example.com
EMAIL_FROM_NAME=FactoryMind by FK Solutions
EMAIL_REPLY_TO=support@example.com
SUPPORT_NOTIFICATION_EMAIL=support@example.com
APP_PUBLIC_URL=http://localhost:5173
EMAIL_MAX_RETRIES=3
EMAIL_RETRY_BASE_SECONDS=5
EMAIL_QUEUE_NAME=transactional-email
EMAIL_RECONCILIATION_SCHEDULING_ENABLED=true
EMAIL_RECONCILIATION_INTERVAL_SECONDS=60
EMAIL_PROCESSING_STALE_SECONDS=300
EMAIL_RECONCILIATION_BATCH_SIZE=100
EMAIL_VERIFICATION_REQUIRED=true
EMAIL_VERIFICATION_EXPIRE_HOURS=24
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS=60
EXPOSE_LOCAL_EMAIL_VERIFICATION_TOKEN=false
```

Resend additionally needs `RESEND_API_KEY`. SMTP needs `SMTP_HOST` and
`SMTP_PORT`; `SMTP_USERNAME` and `SMTP_PASSWORD` must either both be present or
both absent. `SMTP_USE_TLS=true` enables STARTTLS. Secrets belong in the
deployment secret manager, never Git.

Production settings reject `capture` and `disabled`; a deploy must select
`resend` or `smtp`. Provider credentials and sender-domain authorization still
require deployment-owned staging proof before release approval.

`EMAIL_FROM`/`SUPPORT_EMAIL_TO`/`SUPPORT_EMAIL_MAX_ATTEMPTS`/`APP_BASE_URL` remain
accepted as migration aliases, but new deployments should use the names above.

## Identity email policy

New accounts are always persisted with unverified ownership. Registration and
authenticated resend create a cryptographically random credential, persist only
its SHA-256 digest, and queue an encrypted email body. Verification credentials
expire, are single-use, and are invalidated together when ownership succeeds.
Production configuration requires `EMAIL_VERIFICATION_REQUIRED=true`; login and
the current-account/verification endpoints remain available while other bearer
routes return `403` until verification. This preserves account recovery without
granting product access to an unverified address.

Resend is authenticated, rate-limited, and subject to
`EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS`. The public verification endpoint
returns distinct invalid (`422`), expired (`410`), and used (`409`) outcomes.
Raw verification credentials can be returned only in local/development/test
when `EXPOSE_LOCAL_EMAIL_VERIFICATION_TOKEN=true`; production rejects that flag.

Password-reset requests use the same encrypted durable queue and retain the
same generic response for known and unknown addresses. Token-bearing queued
bodies are encrypted using a key derived from `SECRET_KEY`; rotate that key only
after the queue has drained, or outstanding encrypted messages will fail safely
and require a new request.

Team invitations use that same encrypted queue. Create and resend commit the
company-bound invitation before publishing its UUID-only delivery job. Resend
rotates the digest-only credential and observes a persisted cooldown; revocation,
expiry, and acceptance make the link unusable. Local raw invitation links require
`EXPOSE_LOCAL_TEAM_INVITATION_TOKEN=true`, which production rejects.

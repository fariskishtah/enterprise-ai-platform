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
EMAIL_FROM_NAME=FK SOLUTIONS
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
```

Resend additionally needs `RESEND_API_KEY`. SMTP needs `SMTP_HOST` and
`SMTP_PORT`; `SMTP_USERNAME` and `SMTP_PASSWORD` must either both be present or
both absent. `SMTP_USE_TLS=true` enables STARTTLS. Secrets belong in the
deployment secret manager, never Git.

`EMAIL_FROM`/`SUPPORT_EMAIL_TO`/`SUPPORT_EMAIL_MAX_ATTEMPTS`/`APP_BASE_URL` remain
accepted as migration aliases, but new deployments should use the names above.

Email verification and wiring the existing password-reset flow to this queue
are the next identity phase; the foundation does not claim those journeys are
complete yet.

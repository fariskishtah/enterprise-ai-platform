# Support email configuration

Contact Support is authenticated, company scoped, rate limited, idempotent, and
persisted before delivery. Automated tests replace the provider and never send
email.

## Resend configuration

1. Verify the sending domain in Resend.
2. Publish the SPF and DKIM records supplied by Resend.
3. Publish a DMARC policy for the domain; begin with monitored enforcement and
   tighten it after delivery reports are reviewed.
4. Store the API key in the deployment secret manager, not an environment file
   committed to Git.
5. Configure:

```dotenv
EMAIL_PROVIDER=resend
RESEND_API_KEY=<server-only-secret>
EMAIL_FROM_ADDRESS=support@verified.example
EMAIL_FROM_NAME=FactoryMind by FK Solutions
EMAIL_REPLY_TO=support@verified.example
SUPPORT_NOTIFICATION_EMAIL=<support-destination>
EMAIL_MAX_RETRIES=3
EMAIL_RETRY_BASE_SECONDS=5
```

For the current controlled deployment, set `SUPPORT_NOTIFICATION_EMAIL` to the designated
FK SOLUTIONS support mailbox supplied by the operator. The destination is never
returned to the browser.

Resend receives an escaped HTML body and a plain-text body. Reply-To is the
validated authenticated user email. Provider IDs are persisted; API keys,
authorization headers, cookies, passwords, tokens, raw logs, attachments, and
model payloads are never included.

## Queue, failure, and retry behavior

The support request and outbound message are committed before its UUID is sent to
Dramatiq. Retryable failures use bounded exponential backoff; permanent or
exhausted failures change the request to `delivery_failed`. Administrators may
restart a failed delivery. Delivered and closed requests cannot be resent. Each
submission and explicit restart is audited. Local `capture` status is deliberately
not reported as delivered.

Rotate a Resend key in the provider console and deployment secret manager, then
restart the backend and worker services. Treat any exposed key as compromised.

## Testing

Local automated tests use a fake provider. To send one clearly labelled message
from an explicitly configured staging backend:

```bash
API_BASE_URL=https://staging.example \
SUPPORT_TEST_EMAIL='<staging-account>' \
SUPPORT_TEST_PASSWORD='<from-secret-manager>' \
./scripts/send-support-test.sh
```

The script refuses non-HTTPS remote targets and prints only request ID and
delivery status.

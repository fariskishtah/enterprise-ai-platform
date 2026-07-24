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
EMAIL_FROM=support@verified.example
SUPPORT_EMAIL_TO=<support-destination>
SUPPORT_EMAIL_MAX_ATTEMPTS=3
```

For the current controlled deployment, set `SUPPORT_EMAIL_TO` to the designated
FK SOLUTIONS support mailbox supplied by the operator. The destination is never
returned to the browser.

Resend receives an escaped HTML body and a plain-text body. Reply-To is the
validated authenticated user email. Provider IDs are persisted; API keys,
authorization headers, cookies, passwords, tokens, raw logs, attachments, and
model payloads are never included.

## Failure and retry behavior

The request is committed with `submitted` status before delivery. A provider
failure changes it to `delivery_failed` and the UI states that it was saved but
not delivered. Administrators may retry up to the configured maximum. Delivered
and closed requests cannot be resent. Each submission and retry is audited.

Rotate a Resend key in the provider console and deployment secret manager, then
restart only the backend service. Treat any exposed key as compromised.

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

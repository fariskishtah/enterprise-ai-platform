# Production email acceptance

This checklist validates external delivery. It must be executed by an operator
with a verified sender domain, an acceptance mailbox, and credentials held in the
deployment secret manager. Development `capture` mode is not external delivery:
it records status `captured`, never sets `sent_at`, and must not be used in
production.

## Automated contract evidence

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_transactional_email.py \
  tests/test_email_verification.py tests/test_team_invitations.py \
  tests/test_support_requests.py
```

The tests cover every registered template, plain-text and escaped HTML parts,
sender and Reply-To construction, Resend message IDs, SMTP multipart delivery,
invalid-recipient rejection, retryable provider failure, durable status and
attempt state, retry exhaustion, worker execution, capture semantics, metrics,
and redacted logs.

## Credential-backed acceptance

1. Configure either `EMAIL_PROVIDER=resend` with `RESEND_API_KEY`, or
   `EMAIL_PROVIDER=smtp` with the TLS SMTP settings. Configure a verified
   `EMAIL_FROM_ADDRESS`, `EMAIL_FROM_NAME`, optional `EMAIL_REPLY_TO`, and
   `SUPPORT_NOTIFICATION_EMAIL`.
2. Confirm production settings reject `disabled` and `capture`, and restart the
   API and worker without printing environment values.
3. Trigger, one at a time, email verification, password reset, team invitation,
   feedback notification, support notification, payment confirmation, payment
   failure, and subscription cancellation against the designated acceptance
   mailbox.
4. For each message, record only its internal UUID, message type, provider ID,
   timestamps, and final state. Confirm the visible From and Reply-To addresses,
   plain-text part, HTML part, links, and branding in the mailbox.
5. Use the provider's invalid-recipient test address. Confirm a terminal `failed`
   state with a sanitized code and no message body, address, or provider response
   in logs.
6. Temporarily point staging to a provider test that returns 429/4xx transport
   failure. Confirm `retrying`, increasing attempts, bounded backoff, eventual
   success or `retry_limit_reached`, worker metrics, and an email failure alert.
7. Query `transactional_email_delivery_total` and delivery-duration metrics and
   confirm the worker queue drains without duplicate delivery.

## Current result

Live acceptance is blocked. The local environment has no verified sender or
acceptance recipient and no plausibly configured Resend/SMTP credential set.
No external message was attempted. Feedback and billing message types have
rendered template contracts, but their product-event enqueue wiring must be
verified or implemented before those live scenarios can pass.

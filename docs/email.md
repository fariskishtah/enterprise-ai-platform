# Transactional email

The current provider protocol supports disabled mode and Resend for support
requests. Support records remain durable when delivery fails, retain a provider
message ID and bounded attempt count, and can be retried by a company admin.
Password-reset tokens are hashed, expiring, and single-use, and the frontend now
implements request/completion pages. Production reset delivery and email
verification are not yet connected.

Required current variables are `EMAIL_PROVIDER`, `RESEND_API_KEY`, `EMAIL_FROM`,
`SUPPORT_EMAIL_TO`, `SUPPORT_EMAIL_MAX_ATTEMPTS`, and `APP_BASE_URL`; see
`.env.example`. Real credentials and verified sender domains belong in a secret
manager. Before production, add a durable outbound-email queue, capture provider,
plain-text and responsive HTML templates, reply-to/from-name fields, bounded
backoff, delivery metrics, and verification/reset/invitation/billing templates.

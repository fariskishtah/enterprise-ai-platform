# Paymob sandbox acceptance report

Date: 2026-07-29

Classification: **live sandbox acceptance blocked**.

The environment contains no Paymob Secret Key, Public Key, HMAC secret, or
Integration ID. No hosted checkout or external callback was attempted and no
payment success is claimed.

Automated provider and lifecycle coverage validates backend-owned EGP amounts,
Intention payloads, Unified Checkout URL construction, HMAC verification,
fail-closed configuration, retry classification, durable and concurrent event
deduplication, activation only after verified success, failure/cancellation,
refund/reversal precedence, history, worker processing, and card-free logs.

The credential-backed procedure remains in
`docs/production/phase-e-paymob-validation.md`. It must be completed with a
Paymob-issued test account and public HTTPS callback before production approval.

# Security Documentation

This document describes the platform security model.

## Password Hashing

Passwords are hashed with `pwdlib[argon2]` using `PasswordHash.recommended()`. Plaintext passwords are accepted only at registration and login boundaries and are never persisted.

The password policy requires 12 to 128 characters. It deliberately permits spaces
and does not impose composition rules, so long passphrases are supported.

## JWT

The backend issues two JWT types:

- Access tokens with `typ=access`.
- Refresh tokens with `typ=refresh`.

JWTs include:

- `sub`: user UUID.
- `jti`: token UUID.
- `typ`: token purpose.
- `iss`: configured platform issuer.
- `aud`: configured API audience.
- `iat`: issued-at timestamp.
- `exp`: expiration timestamp.

Access tokens also include `email` and `role` claims. Protected routes validate the
signature, issuer, audience, expiry, required claims, expected token purpose, active
user state, and RBAC role. Access and refresh tokens are not interchangeable.

## Refresh Tokens

Refresh tokens are stateful. The raw refresh token is returned to the client once. The backend stores only a SHA-256 digest plus metadata.

Refresh behavior:

- Decode and validate refresh JWT.
- Find matching `jti` and token digest.
- Reject revoked or expired tokens.
- Revoke the used token.
- Issue a new access token and refresh token.

Logout revokes the supplied refresh token.

## RBAC

Supported roles:

- `admin`: full manufacturing CRUD access, including soft delete.
- `engineer`: create, update, and read manufacturing resources.
- `operator`: read-only manufacturing access.

RBAC is enforced through the `require_roles` FastAPI dependency.

## API Boundary Hardening

- Registration, login, and token refresh have a narrow Redis-backed per-client
  fixed-window rate limit. Redis failures preserve authentication availability and
  emit a bounded operational error without request data.
- CORS uses an explicit settings-driven origin allowlist; wildcard origins are not
  accepted and production settings reject local origins.
- API responses receive clickjacking, MIME-sniffing, referrer, permissions, and CSP
  protections. Development documentation paths omit CSP so Swagger remains usable.
- Authentication responses use `Cache-Control: no-store`.
- Structured security audit events cover login outcomes, rate-limit denials, and
  privileged authorization denials without user identifiers or secrets.

## Threat Model

Primary risks addressed:

- Credential theft: password hashes use Argon2 rather than plaintext or fast hashes.
- Refresh-token replay: refresh tokens rotate and old tokens are revoked.
- Token tampering or cross-use: JWT signature, issuer, audience, expiry, and purpose
  are validated before claims are trusted.
- Unauthorized access: protected routes require valid bearer access tokens.
- Privilege misuse: manufacturing mutations are role-gated.
- Duplicate company identity: company names are normalized and uniquely indexed.
- Accidental destructive deletion: manufacturing delete operations use soft-delete timestamps.

Risks intentionally deferred:

- Account recovery.
- Email verification.
- Multi-factor authentication.
- Device/session management UI.
- Fine-grained per-company authorization.

## Security Best Practices

- Use a high-entropy `SECRET_KEY` in every environment.
- Serve production traffic only over HTTPS.
- Store tokens securely on clients.
- Keep access-token lifetimes short.
- Rotate secrets through deployment automation.
- Run Alembic migrations before serving traffic.
- Do not log plaintext passwords, access tokens, or refresh tokens.
- Restrict admin accounts to users who need delete permissions.

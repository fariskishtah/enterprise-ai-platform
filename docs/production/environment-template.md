# Production environment template

Store the real values in the deployment secret manager or an untracked
root-readable environment file. Values below are placeholders.

```dotenv
APP_ENV=production
ENVIRONMENT=production
APP_PUBLIC_URL=https://platform.example
API_BASE_URL=https://platform.example/api
ALLOWED_HOSTS=["platform.example"]
CORS_ALLOWED_ORIGINS=["https://platform.example"]
CORS_ALLOW_CREDENTIALS=true
COOKIE_SECURE=true
COOKIE_SAMESITE=strict
COOKIE_DOMAIN=platform.example
ENABLE_API_DOCS=false
DEMO_TOOLS_ENABLED=false

DATABASE_URL=postgresql+psycopg://<user>:<encoded-secret>@postgres:5432/<database>
REDIS_URL=redis://redis:6379/0
SECRET_KEY=<independently-generated-high-entropy-secret>
JWT_ISSUER=<deployment-specific-issuer>
JWT_AUDIENCE=<deployment-specific-audience>

EMAIL_PROVIDER=resend
RESEND_API_KEY=<server-only-secret>
EMAIL_FROM_ADDRESS=support@verified.example
EMAIL_FROM_NAME=FactoryMind by FK Solutions
EMAIL_REPLY_TO=support@verified.example
SUPPORT_NOTIFICATION_EMAIL=<support-mailbox>
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
EMAIL_MAX_RETRIES=3
EMAIL_RETRY_BASE_SECONDS=5
EMAIL_QUEUE_NAME=transactional-email
EMAIL_RECONCILIATION_SCHEDULING_ENABLED=true
EMAIL_RECONCILIATION_INTERVAL_SECONDS=60
EMAIL_PROCESSING_STALE_SECONDS=300
EMAIL_RECONCILIATION_BATCH_SIZE=100

PAYMENT_PROVIDER=disabled
PAYMOB_API_KEY=
PAYMOB_SECRET_KEY=
PAYMOB_PUBLIC_KEY=
PAYMOB_HMAC_SECRET=
PAYMOB_INTEGRATION_ID=
PAYMOB_MERCHANT_ID=
PAYMOB_IFRAME_ID=
PAYMOB_BASE_URL=https://accept.paymob.com
PAYMOB_WEBHOOK_URL=https://platform.example/api/billing/webhooks/paymob
PAYMENT_SUCCESS_URL=https://platform.example/settings/billing/return
PAYMENT_FAILURE_URL=https://platform.example/settings/billing/return
PAYMENT_CURRENCY=EGP
PAYMENT_SANDBOX_MODE=true
PAYMENT_HTTP_TIMEOUT_SECONDS=10
BILLING_WEBHOOK_QUEUE_NAME=billing-webhooks
BILLING_WEBHOOK_MAX_RETRIES=5
BILLING_GRACE_PERIOD_DAYS=7
BILLING_INCOMPLETE_EXPIRY_HOURS=24
BILLING_SUSPENSION_EXPIRY_DAYS=30
BILLING_ENTITLEMENTS_ENFORCED=true

PASSWORD_RESET_EXPIRE_MINUTES=30
EXPOSE_LOCAL_PASSWORD_RESET_TOKEN=false
EMAIL_VERIFICATION_REQUIRED=true
EMAIL_VERIFICATION_EXPIRE_HOURS=24
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS=60
EXPOSE_LOCAL_EMAIL_VERIFICATION_TOKEN=false
TEAM_INVITATION_EXPIRE_HOURS=72
TEAM_INVITATION_RESEND_COOLDOWN_SECONDS=60
EXPOSE_LOCAL_TEAM_INVITATION_TOKEN=false
AUTH_RATE_LIMIT_ENABLED=true
MUTATION_RATE_LIMIT_ENABLED=true

DATASET_STORAGE_ROOT=/app/data/datasets
MODEL_ARTIFACT_ROOT=/app/ml/model-artifacts
AI_ARTIFACT_ROOT=/app/ml/ai-artifacts
MLFLOW_TRACKING_URI=file:/app/mlruns

BACKUP_TARGET=s3
BACKUP_S3_URI=s3://<bucket>/<prefix>
BACKUP_S3_ENDPOINT_URL=https://<s3-compatible-endpoint>
BACKUP_S3_SSE=AES256
BACKUP_ENCRYPTION_PASSPHRASE=<independent-backup-secret>

HTTPS_DOMAIN=platform.example
PUBLIC_BASE_URL=https://platform.example
PUBLIC_HTTP_PORT=80
PUBLIC_HTTPS_PORT=443
```

The S3 values above configure encrypted backup transport. They do not turn the
application's mounted dataset/model/report storage into object storage.

# Production environment template

Store the real values in the deployment secret manager or an untracked
root-readable environment file. Values below are placeholders.

```dotenv
APP_ENV=production
ENVIRONMENT=production
APP_BASE_URL=https://platform.example
API_BASE_URL=https://platform.example/api
ALLOWED_HOSTS=["platform.example"]
CORS_ALLOWED_ORIGINS=["https://platform.example"]
COOKIE_SECURE=true
COOKIE_SAMESITE=strict
ENABLE_API_DOCS=false
DEMO_TOOLS_ENABLED=false

DATABASE_URL=postgresql+psycopg://<user>:<encoded-secret>@postgres:5432/<database>
REDIS_URL=redis://redis:6379/0
SECRET_KEY=<independently-generated-high-entropy-secret>
JWT_ISSUER=<deployment-specific-issuer>
JWT_AUDIENCE=<deployment-specific-audience>

EMAIL_PROVIDER=resend
RESEND_API_KEY=<server-only-secret>
EMAIL_FROM=support@verified.example
SUPPORT_EMAIL_TO=fkishtah@gmail.com
SUPPORT_EMAIL_MAX_ATTEMPTS=3

PASSWORD_RESET_EXPIRE_MINUTES=30
EXPOSE_LOCAL_PASSWORD_RESET_TOKEN=false
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

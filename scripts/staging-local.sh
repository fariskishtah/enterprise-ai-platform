#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_NAME="ai-manufacturing-staging-validation"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly STATE_DIR="$REPO_ROOT/.staging-validation"
readonly ENV_FILE="$STATE_DIR/environment"
readonly MARKER_FILE="$STATE_DIR/owned-by-staging-local"

usage() {
  echo "Usage: $0 start|seed|stop|status|clean" >&2
}

generate_environment() {
  command -v openssl >/dev/null 2>&1 || {
    echo "openssl is required to generate disposable credentials." >&2
    exit 2
  }
  mkdir -p -- "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  local database_password secret_key
  database_password="$(openssl rand -hex 24)"
  secret_key="$(openssl rand -hex 32)"
  umask 077
  {
    printf 'POSTGRES_DB=staging_validation\n'
    printf 'POSTGRES_USER=staging_validation\n'
    printf 'POSTGRES_PASSWORD=%s\n' "$database_password"
    printf 'DATABASE_URL=postgresql+psycopg://staging_validation:%s@postgres:5432/staging_validation\n' "$database_password"
    printf 'REDIS_URL=redis://redis:6379/0\n'
    printf 'SECRET_KEY=%s\n' "$secret_key"
    printf 'JWT_ISSUER=staging-validation\n'
    printf 'JWT_AUDIENCE=staging-validation-browser\n'
    printf 'JWT_ALGORITHM=HS256\n'
    printf 'ENVIRONMENT=staging\n'
    printf 'CORS_ALLOWED_ORIGINS=["http://127.0.0.1:18080"]\n'
    printf 'TRUSTED_PROXY_IPS=*\n'
    printf 'PUBLIC_HTTP_PORT=18080\n'
    printf 'AI_DEFAULT_REGISTERED_MODEL_PREFIX=staging_validation\n'
    printf 'ACCESS_TOKEN_EXPIRE_MINUTES=15\n'
    printf 'REFRESH_TOKEN_EXPIRE_DAYS=1\n'
    printf 'GRAFANA_ADMIN_USER=staging-validation\n'
    printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 24)"
  } >"$ENV_FILE"
  : >"$MARKER_FILE"
}

compose() {
  docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" \
    -f "$REPO_ROOT/docker-compose.yml" \
    -f "$REPO_ROOT/docker-compose.prod.yml" \
    -f "$REPO_ROOT/docker-compose.staging.yml" "$@"
}

wait_for_runtime() {
  local deadline=$((SECONDS + 240))
  until curl --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:18080/api/ready >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      compose ps >&2
      echo "Staging-like runtime did not become ready." >&2
      exit 1
    fi
    sleep 2
  done
}

action="${1:-}"
case "$action" in
  start)
    [[ -f "$ENV_FILE" ]] || generate_environment
    compose config --quiet
    compose up --detach --build postgres redis migrate backend training-worker frontend reverse-proxy
    wait_for_runtime
    docs_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
      http://127.0.0.1:18080/api/docs)"
    [[ "$docs_status" == "404" ]] || {
      echo "API documentation unexpectedly returned HTTP $docs_status." >&2
      exit 1
    }
    echo "Staging-like runtime ready at http://127.0.0.1:18080"
    ;;
  seed)
    [[ -f "$ENV_FILE" ]] || { echo "Start the staging runtime first." >&2; exit 1; }
    for variable in E2E_ADMIN_EMAIL E2E_ENGINEER_EMAIL E2E_OPERATOR_EMAIL E2E_PASSWORD; do
      [[ -n "${!variable:-}" ]] || { echo "$variable is required." >&2; exit 2; }
    done
    compose exec -T \
      -e E2E_ADMIN_EMAIL -e E2E_ENGINEER_EMAIL -e E2E_OPERATOR_EMAIL -e E2E_PASSWORD \
      backend python - <"$REPO_ROOT/scripts/seed_staging_users.py"
    compose exec -T \
      -e DEMO_API_BASE_URL=http://backend:8000 \
      -e DEMO_EMAIL="$E2E_ENGINEER_EMAIL" \
      -e DEMO_PASSWORD="$E2E_PASSWORD" \
      backend python - <"$REPO_ROOT/scripts/seed_demo.py"
    echo "Disposable role accounts and deterministic workflow data are ready."
    ;;
  stop)
    [[ -f "$ENV_FILE" ]] || { echo "No staging runtime state exists."; exit 0; }
    compose down --remove-orphans
    echo "Staging-like runtime stopped; disposable volumes were retained."
    ;;
  status)
    [[ -f "$ENV_FILE" ]] || { echo "No staging runtime state exists."; exit 1; }
    compose ps
    ;;
  clean)
    [[ -f "$MARKER_FILE" && -f "$ENV_FILE" ]] || {
      echo "Refusing cleanup without the staging ownership marker." >&2
      exit 1
    }
    compose down --volumes --remove-orphans
    rm -f -- "$ENV_FILE" "$MARKER_FILE"
    rmdir "$STATE_DIR" 2>/dev/null || true
    echo "Owned staging containers, networks, and disposable volumes removed."
    ;;
  *)
    usage
    exit 2
    ;;
esac

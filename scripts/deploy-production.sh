#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_NAME="ai-manufacturing-production"
ENV_FILE=".env.production"
HEALTH_TIMEOUT="${PRODUCTION_HEALTH_TIMEOUT_SECONDS:-180}"

usage() {
  echo "Usage: $0 [--env-file FILE] [--timeout SECONDS]" >&2
}

while (($#)); do
  case "$1" in
    --env-file)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      ENV_FILE="$2"
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      HEALTH_TIMEOUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      usage
      exit 2
      ;;
    *)
      [[ "$ENV_FILE" == ".env.production" ]] || { usage; exit 2; }
      ENV_FILE="$1"
      shift
      ;;
  esac
done

[[ "$HEALTH_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || {
  echo "Error: timeout must be a positive integer." >&2
  exit 2
}

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" || "$(pwd -P)" != "$(cd "$REPO_ROOT" && pwd -P)" || \
      ! -f docker-compose.yml || ! -f docker-compose.prod.yml ]]; then
  echo "Error: run this script from the repository root." >&2
  exit 1
fi

if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$REPO_ROOT/$ENV_FILE"
fi
[[ -f "$ENV_FILE" ]] || {
  echo "Error: production environment file was not found." >&2
  exit 1
}

COMPOSE=(
  docker compose
  --project-name "$PROJECT_NAME"
  --env-file "$ENV_FILE"
  -f docker-compose.yml
  -f docker-compose.prod.yml
)

echo "Validating production Compose configuration..."
"${COMPOSE[@]}" config --quiet

echo "Pulling pinned runtime images and building application images..."
"${COMPOSE[@]}" pull --ignore-buildable
"${COMPOSE[@]}" build --pull

echo "Starting the production data services..."
"${COMPOSE[@]}" up -d --no-build --wait \
  --wait-timeout "$HEALTH_TIMEOUT" postgres redis

echo "Applying database migrations..."
"${COMPOSE[@]}" run --rm --no-deps backend alembic upgrade head

echo "Starting production services..."
"${COMPOSE[@]}" up -d --no-build

"$REPO_ROOT/scripts/verify-production.sh" \
  --env-file "$ENV_FILE" \
  --timeout "$HEALTH_TIMEOUT"

echo "Production deployment completed successfully."

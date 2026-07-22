#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_NAME="ai-manufacturing-production"
REVISION=""
ENV_FILE=".env.production"
HEALTH_TIMEOUT="${PRODUCTION_HEALTH_TIMEOUT_SECONDS:-180}"

usage() {
  echo "Usage: $0 REVISION [--env-file FILE] [--timeout SECONDS]" >&2
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
      if [[ -z "$REVISION" ]]; then
        REVISION="$1"
      elif [[ "$ENV_FILE" == ".env.production" ]]; then
        ENV_FILE="$1"
      else
        usage
        exit 2
      fi
      shift
      ;;
  esac
done

[[ -n "$REVISION" ]] || { usage; exit 2; }
[[ "$HEALTH_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || {
  echo "Error: timeout must be a positive integer." >&2
  exit 2
}

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" || "$(pwd -P)" != "$(cd "$REPO_ROOT" && pwd -P)" || \
      ! -f docker-compose.yml ]]; then
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

CURRENT_COMPOSE=(
  docker compose
  --project-name "$PROJECT_NAME"
  --env-file "$ENV_FILE"
  -f "$REPO_ROOT/docker-compose.yml"
  -f "$REPO_ROOT/docker-compose.prod.yml"
)
current_postgres_id="$("${CURRENT_COMPOSE[@]}" ps -q postgres)"
if [[ -z "$current_postgres_id" ]]; then
  echo "Error: the current production PostgreSQL container is not running." >&2
  exit 1
fi
current_postgres_image="$(docker inspect --format '{{.Config.Image}}' "$current_postgres_id")"

RESOLVED_REVISION="$(git rev-parse --verify --end-of-options "${REVISION}^{commit}" 2>/dev/null)" || {
  echo "Error: supplied rollback revision is not a local Git commit." >&2
  exit 1
}

ROLLBACK_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/ai-production-rollback.XXXXXX")"
ROLLBACK_ROOT="$ROLLBACK_PARENT/source"
cleanup() {
  if [[ -d "$ROLLBACK_ROOT" ]]; then
    git -C "$REPO_ROOT" worktree remove --force "$ROLLBACK_ROOT" >/dev/null 2>&1 || true
  fi
  rmdir "$ROLLBACK_PARENT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Preparing the supplied revision in an isolated worktree..."
git worktree add --quiet --detach "$ROLLBACK_ROOT" "$RESOLVED_REVISION"
[[ -f "$ROLLBACK_ROOT/docker-compose.yml" && \
   -f "$ROLLBACK_ROOT/docker-compose.prod.yml" && \
   -f "$ROLLBACK_ROOT/scripts/verify-production.sh" ]] || {
  echo "Error: revision does not contain the production deployment configuration." >&2
  exit 1
}

cd "$ROLLBACK_ROOT"
COMPOSE=(
  docker compose
  --project-name "$PROJECT_NAME"
  --env-file "$ENV_FILE"
  -f docker-compose.yml
  -f docker-compose.prod.yml
)

echo "Validating rollback Compose configuration..."
"${COMPOSE[@]}" config --quiet
rollback_postgres_image="$({
  "${COMPOSE[@]}" config | awk '
    $0 == "  postgres:" { in_postgres = 1; next }
    in_postgres && $0 ~ /^    image: / {
      sub(/^    image: /, "")
      print
      exit
    }
    in_postgres && $0 ~ /^  [^ ]/ { exit }
  '
})"
if [[ -z "$rollback_postgres_image" || \
      "$rollback_postgres_image" != "$current_postgres_image" ]]; then
  echo "Error: refusing rollback because the target PostgreSQL image is not compatible with the running database image." >&2
  echo "Use a roll-forward application revision that retains the current PostgreSQL image." >&2
  exit 1
fi

echo "Pulling and building the supplied revision..."
"${COMPOSE[@]}" pull --ignore-buildable
"${COMPOSE[@]}" build --pull

echo "Starting the supplied revision without changing persistent volumes or migrations..."
"${COMPOSE[@]}" up -d --no-build

bash scripts/verify-production.sh \
  --env-file "$ENV_FILE" \
  --timeout "$HEALTH_TIMEOUT"

echo "Production rollback completed successfully; database migrations were left unchanged."

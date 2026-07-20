#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_NAME="ai-manufacturing-production"
ENV_FILE=".env.production"

usage() {
  echo "Usage: $0 [--env-file FILE]" >&2
}

while (($#)); do
  case "$1" in
    --env-file)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      ENV_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

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
  -f docker-compose.https.yml
)

container_id="$("${COMPOSE[@]}" ps -q reverse-proxy)"
[[ -n "$container_id" ]] && [[ "$(docker inspect -f '{{.State.Running}}' "$container_id")" == "true" ]] || {
  echo "Error: the production reverse-proxy container is not running." >&2
  exit 1
}

echo "Validating the active reverse-proxy configuration..."
"${COMPOSE[@]}" exec -T reverse-proxy nginx -t
echo "Reloading only the production reverse proxy..."
"${COMPOSE[@]}" exec -T reverse-proxy nginx -s reload
echo "Production reverse proxy reloaded successfully."

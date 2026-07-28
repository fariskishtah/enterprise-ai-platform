#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

compose=(docker compose)
if [[ -n "${DEMO_COMPOSE_PROJECT:-}" ]]; then
  compose+=(-p "$DEMO_COMPOSE_PROJECT")
fi

if ! "${compose[@]}" ps --status running --services | grep -qx backend; then
  echo "Backend is not running. Start the local stack first:" >&2
  echo "  docker compose up -d postgres redis backend training-worker" >&2
  exit 1
fi

: "${DEMO_EMAIL:?Set DEMO_EMAIL to a disposable local-only account}"
: "${DEMO_PASSWORD:?Set DEMO_PASSWORD to a unique local-only password}"

"${compose[@]}" exec -T \
  -e ENABLE_DEVELOPMENT_SEED=true \
  -e DEMO_API_BASE_URL="${DEMO_API_BASE_URL:-http://backend:8000}" \
  -e DEMO_EMAIL \
  -e DEMO_PASSWORD \
  backend python - < scripts/seed_demo.py

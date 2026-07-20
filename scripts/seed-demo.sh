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

"${compose[@]}" exec -T \
  -e DEMO_API_BASE_URL="${DEMO_API_BASE_URL:-http://backend:8000}" \
  -e DEMO_EMAIL="${DEMO_EMAIL:-demo@example.com}" \
  -e DEMO_PASSWORD="${DEMO_PASSWORD:-LocalDemoPassword1!}" \
  backend python - < scripts/seed_demo.py

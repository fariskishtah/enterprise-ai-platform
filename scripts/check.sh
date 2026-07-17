#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_VENV_BIN="$ROOT_DIR/backend/.venv/bin"

if [[ -x "$BACKEND_VENV_BIN/ruff" ]]; then
  RUFF="$BACKEND_VENV_BIN/ruff"
  BLACK="$BACKEND_VENV_BIN/black"
  MYPY="$BACKEND_VENV_BIN/mypy"
  PYTEST="$BACKEND_VENV_BIN/pytest"
else
  RUFF="ruff"
  BLACK="black"
  MYPY="mypy"
  PYTEST="pytest"
fi

cd "$ROOT_DIR/backend"
"$RUFF" check .
"$BLACK" --check .
"$MYPY" app
"$PYTEST"

cd "$ROOT_DIR/frontend"
npm run lint
npm run build
npm run format
npm audit

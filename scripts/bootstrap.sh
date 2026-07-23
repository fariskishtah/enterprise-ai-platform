#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3.12 >/dev/null 2>&1 || {
  echo "Python 3.12 is required." >&2
  exit 2
}
command -v node >/dev/null 2>&1 || {
  echo "Node.js 22 is required." >&2
  exit 2
}
if [[ "$(node -p 'process.versions.node.split(".")[0]')" != "22" ]]; then
  echo "Node.js 22 is required; detected $(node --version)." >&2
  exit 2
fi

cd "$ROOT_DIR/backend"
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements/dev.lock
python -m pip install --no-deps --no-build-isolation -e .

cd "$ROOT_DIR/frontend"
npm ci

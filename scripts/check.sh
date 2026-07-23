#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "scripts/check.sh is the compatibility alias for the fast release gate."
exec "$ROOT_DIR/scripts/validate-release.sh" --fast --allow-dirty

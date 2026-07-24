#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BACKEND_DIR="$REPO_ROOT/backend"
readonly FRONTEND_DIR="$REPO_ROOT/frontend"
readonly EVIDENCE_DIR="$REPO_ROOT/artifacts/release"
readonly TRIVY_CACHE_DIR="$REPO_ROOT/artifacts/trivy-cache"
MODE="fast"
ALLOW_DIRTY=false
STAGING_STARTED=false

usage() {
  cat <<'USAGE'
Usage: ./scripts/validate-release.sh --fast|--full [--allow-dirty]

  --fast         Governance, static analysis, frontend release build, and config checks.
  --full         Fast checks plus all tests, security/image scans, SBOMs, and a disposable
                 staging runtime with real-backend browser and smoke validation.
  --allow-dirty  Permit tracked/untracked changes while developing release evidence.
USAGE
}

while (($#)); do
  case "$1" in
    --fast|--full)
      MODE="${1#--}"
      shift
      ;;
    --allow-dirty)
      ALLOW_DIRTY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

section() {
  printf '\n== %s ==\n' "$1"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command is unavailable: $1" >&2
    exit 2
  }
}

cleanup() {
  if [[ "$STAGING_STARTED" == true ]]; then
    "$REPO_ROOT/scripts/staging-local.sh" clean
  fi
}
trap cleanup EXIT

cd "$REPO_ROOT"
require_command git
require_command node
require_command npm
require_command docker
if [[ "$(node -p 'process.versions.node.split(".")[0]')" != "22" ]]; then
  echo "Release validation requires Node.js 22; detected $(node --version)." >&2
  exit 2
fi

PYTHON="$BACKEND_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Python 3.12 environment missing. Run ./scripts/bootstrap.sh first." >&2
  exit 2
fi
if [[ "$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.12" ]]; then
  echo "backend/.venv must use Python 3.12." >&2
  exit 2
fi
export PATH="$BACKEND_DIR/.venv/bin:$PATH"
mkdir -p "$EVIDENCE_DIR" "$TRIVY_CACHE_DIR"

section "Repository and governance"
git diff --check
if [[ "$ALLOW_DIRTY" == false && -n "$(git status --short)" ]]; then
  echo "Release validation requires a clean working tree; use --allow-dirty only during development." >&2
  exit 1
fi
"$PYTHON" scripts/check-release-version.py
"$PYTHON" scripts/check-release-docs.py

section "Shell and Python syntax"
while IFS= read -r script; do
  bash -n "$script"
done < <(find scripts -maxdepth 1 -type f -name '*.sh' -print | sort)
"$PYTHON" -m compileall -q backend/app scripts

section "Backend static validation"
(
  cd "$BACKEND_DIR"
  ruff check .
  black --check .
  mypy app
  python -m pip check
)

section "Frontend static validation and performance"
(
  cd "$FRONTEND_DIR"
  npm run lint
  npm run format
  npm run build:release
)

section "Compose configuration"
docker compose --env-file .env.example -f docker-compose.yml config -q
docker compose --env-file .env.example \
  -f docker-compose.yml -f docker-compose.staging.yml config -q
docker compose --env-file .env.example \
  -f docker-compose.yml -f docker-compose.prod.yml config -q
docker compose --env-file .env.example \
  -f docker-compose.yml -f docker-compose.prod.yml \
  --profile observability config -q

if [[ "$MODE" == "fast" ]]; then
  echo
  echo "Fast release validation passed. Full tests, runtime smoke, image scans, and SBOM generation were not requested."
  exit 0
fi

section "Backend tests and migration chain"
(
  cd "$BACKEND_DIR"
  pytest -q
  alembic heads
)

section "Frontend browser and accessibility tests"
(
  cd "$FRONTEND_DIR"
  npx playwright install chromium
  npm run test:e2e
)

section "Dependency and source security"
(
  cd "$BACKEND_DIR"
  python -m pip_audit -r requirements/base.lock --progress-spinner off \
    --format json --output "$EVIDENCE_DIR/pip-audit.json"
  python -m pip_audit --local --progress-spinner off \
    --ignore-vuln PYSEC-2026-2120 \
    --ignore-vuln PYSEC-2026-2121
  bandit -c pyproject.toml -r app -ll -f json -o "$EVIDENCE_DIR/bandit.json"
  pip-licenses --format=json --output-file="$EVIDENCE_DIR/backend-licenses.json"
)
(
  cd "$FRONTEND_DIR"
  npm audit --audit-level=high --json >"$EVIDENCE_DIR/npm-audit.json"
  node scripts/write-license-inventory.mjs "$EVIDENCE_DIR/frontend-licenses.json"
)
docker run --rm --volume "$REPO_ROOT:/repo" \
  ghcr.io/gitleaks/gitleaks:v8.30.1 \
  detect --source=/repo --redact=100 --no-banner \
  --report-format=sarif --report-path=/repo/artifacts/release/gitleaks.sarif
docker run --rm --volume "$REPO_ROOT:/src" semgrep/semgrep:1.164.0 \
  semgrep scan --config=p/python --config=p/typescript --error --metrics=off \
  --sarif-output=/src/artifacts/release/semgrep.sarif \
  backend/app frontend/src scripts
docker run --rm --volume "$REPO_ROOT:/repo" \
  --volume "$TRIVY_CACHE_DIR:/root/.cache/" aquasec/trivy:0.70.0 \
  fs --skip-version-check --scanners vuln,misconfig \
  --severity HIGH,CRITICAL --exit-code 1 \
  --format json --output /repo/artifacts/release/trivy-filesystem.json /repo

section "Candidate images, image security, and SBOM"
for image in backend frontend reverse-proxy; do
  docker build --file "docker/$image/Dockerfile" --tag "ai-platform-$image:release-validation" .
  docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock \
    --volume "$EVIDENCE_DIR:/out" anchore/syft:v1.44.0 \
    "ai-platform-$image:release-validation" \
    --output "spdx-json=/out/$image-sbom.spdx.json"
  docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock \
    --volume "$TRIVY_CACHE_DIR:/root/.cache/" \
    --volume "$EVIDENCE_DIR:/out" aquasec/trivy:0.70.0 \
    image --scanners vuln,secret,misconfig --severity HIGH,CRITICAL \
    --skip-version-check --exit-code 0 --format json \
    --output "/out/$image-trivy.json" \
    "ai-platform-$image:release-validation"
  docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock \
    --volume "$TRIVY_CACHE_DIR:/root/.cache/" \
    --volume "$EVIDENCE_DIR:/out" aquasec/trivy:0.70.0 \
    image --scanners vuln,secret,misconfig --severity HIGH,CRITICAL \
    --skip-version-check --ignore-unfixed --exit-code 1 --format json \
    --output "/out/$image-trivy-actionable.json" \
    "ai-platform-$image:release-validation"
done

section "Nginx configuration"
docker run --rm --user 101:101 --cap-drop ALL --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m,uid=101,gid=101,mode=1770 \
  --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 \
  --entrypoint nginx ai-platform-reverse-proxy:release-validation -t
docker run --rm --user 101:101 --cap-drop ALL --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m,uid=101,gid=101,mode=1770 \
  --entrypoint nginx ai-platform-frontend:release-validation -t

section "Disposable staging runtime, real-backend browser, and smoke"
export E2E_ADMIN_EMAIL="admin@release-validation.example"
export E2E_ENGINEER_EMAIL="engineer@release-validation.example"
export E2E_OPERATOR_EMAIL="operator@release-validation.example"
E2E_PASSWORD="$(openssl rand -hex 18)Aa1!"
export E2E_PASSWORD
STAGING_STARTED=true
"$REPO_ROOT/scripts/staging-local.sh" start
"$REPO_ROOT/scripts/staging-local.sh" seed
"$REPO_ROOT/scripts/staging-local.sh" seed

section "Encrypted backup and disposable recovery"
BACKUP_COMPOSE_PROJECT_NAME=ai-manufacturing-staging-validation \
  BACKUP_COMPOSE_ENV_FILE="$REPO_ROOT/.staging-validation/environment" \
  BACKUP_COMPOSE_FILES="$REPO_ROOT/docker-compose.yml:$REPO_ROOT/docker-compose.prod.yml:$REPO_ROOT/docker-compose.staging.yml" \
  BACKUP_TARGET=local \
  BACKUP_DIR="$EVIDENCE_DIR/backups" \
  BACKUP_ENCRYPTION_PASSPHRASE="$E2E_PASSWORD" \
  "$REPO_ROOT/scripts/backup-production.sh"
latest_backup="$(find "$EVIDENCE_DIR/backups" -maxdepth 1 -type f \
  -name 'pilot-*.tar.gz.enc' -print | sort | tail -1)"
[[ -n "$latest_backup" ]] || {
  echo "The encrypted backup was not produced." >&2
  exit 1
}
BACKUP_COMPOSE_PROJECT_NAME=ai-manufacturing-staging-validation \
  BACKUP_COMPOSE_ENV_FILE="$REPO_ROOT/.staging-validation/environment" \
  BACKUP_COMPOSE_FILES="$REPO_ROOT/docker-compose.yml:$REPO_ROOT/docker-compose.prod.yml:$REPO_ROOT/docker-compose.staging.yml" \
  BACKUP_ENCRYPTION_PASSPHRASE="$E2E_PASSWORD" \
  RESTORE_EVIDENCE_DIR="$EVIDENCE_DIR" \
  "$REPO_ROOT/scripts/restore-validation.sh" "$latest_backup"

(
  cd "$FRONTEND_DIR"
  E2E_BASE_URL=http://127.0.0.1:18080 \
    E2E_EXTERNAL_SERVER=1 E2E_REAL_BACKEND=true \
    npm run test:e2e -- real-backend.spec.ts
)
BASE_URL=http://127.0.0.1:18080 \
  SMOKE_ALLOW_HTTP=true \
  SMOKE_DOCS_EXPECTED_STATUS=404 \
  SMOKE_EMAIL="$E2E_ENGINEER_EMAIL" \
  SMOKE_PASSWORD="$E2E_PASSWORD" \
  "$REPO_ROOT/scripts/smoke-production.sh"

echo
echo "Full release validation passed. Evidence is in artifacts/release."

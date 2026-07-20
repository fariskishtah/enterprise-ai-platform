#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_NAME="ai-manufacturing-production"
readonly CORE_SERVICES=(postgres redis backend training-worker frontend reverse-proxy)
ENV_FILE=".env.production"
HEALTH_TIMEOUT="${PRODUCTION_HEALTH_TIMEOUT_SECONDS:-180}"
HTTPS_ENABLED=false

usage() {
  echo "Usage: $0 [--env-file FILE] [--timeout SECONDS] [--https]" >&2
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
    --https)
      HTTPS_ENABLED=true
      shift
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

command -v curl >/dev/null 2>&1 || {
  echo "Error: curl is required for production verification." >&2
  exit 1
}

COMPOSE=(
  docker compose
  --project-name "$PROJECT_NAME"
  --env-file "$ENV_FILE"
  -f docker-compose.yml
  -f docker-compose.prod.yml
)

if [[ "$HTTPS_ENABLED" == true ]]; then
  COMPOSE+=(-f docker-compose.https.yml)
fi

"${COMPOSE[@]}" config --quiet

deadline=$((SECONDS + HEALTH_TIMEOUT))
while :; do
  pending=()
  for service in "${CORE_SERVICES[@]}"; do
    container_id="$("${COMPOSE[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      pending+=("$service (not running)")
      continue
    fi

    state="$(docker inspect --format \
      '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$container_id")"
    case "$state" in
      healthy|running) ;;
      unhealthy|exited|dead)
        echo "Error: production service $service is $state." >&2
        exit 1
        ;;
      *) pending+=("$service ($state)") ;;
    esac
  done

  ((${#pending[@]} == 0)) && break
  if ((SECONDS >= deadline)); then
    echo "Error: timed out waiting for production services: ${pending[*]}." >&2
    exit 1
  fi
  sleep 2
done

echo "Checking internal data and application health..."
"${COMPOSE[@]}" exec -T postgres \
  sh -ec 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${COMPOSE[@]}" exec -T redis redis-cli ping >/dev/null
"${COMPOSE[@]}" exec -T reverse-proxy \
  wget -q --spider http://backend:8000/health
"${COMPOSE[@]}" exec -T reverse-proxy \
  wget -q --spider http://frontend:8080/healthz

assert_not_published() {
  local service="$1"
  local container_port="$2"
  local container_id
  local published=""
  container_id="$("${COMPOSE[@]}" ps -q "$service")"
  [[ -z "$container_id" ]] || \
    published="$(docker port "$container_id" "${container_port}/tcp" 2>/dev/null || true)"
  if [[ -n "$published" ]]; then
    echo "Error: production service $service unexpectedly publishes a host port." >&2
    exit 1
  fi
}

echo "Checking production port isolation..."
assert_not_published backend 8000
assert_not_published frontend 8080
assert_not_published postgres 5432
assert_not_published redis 6379
assert_not_published alertmanager 9093
assert_not_published prometheus 9090
assert_not_published loki 3100
assert_not_published alloy 12345
assert_not_published tempo 3200
assert_not_published grafana 3000

proxy_container_id="$("${COMPOSE[@]}" ps -q reverse-proxy)"
published_address="$(docker port "$proxy_container_id" 8080/tcp | sed -n '1p')"
public_port="${published_address##*:}"
[[ "$public_port" =~ ^[0-9]+$ ]] || {
  echo "Error: reverse proxy does not publish a valid HTTP port." >&2
  exit 1
}

echo "Checking public proxy, frontend, and backend routes..."
curl --fail --silent --show-error --output /dev/null \
  --connect-timeout 5 --max-time 15 "http://127.0.0.1:${public_port}/healthz"
curl --fail --silent --show-error --output /dev/null \
  --connect-timeout 5 --max-time 15 "http://127.0.0.1:${public_port}/"
curl --fail --silent --show-error --output /dev/null \
  --connect-timeout 5 --max-time 15 "http://127.0.0.1:${public_port}/api/health"

if [[ "$HTTPS_ENABLED" == true ]]; then
  read_env_value() {
    local name="$1"
    local value="${!name-}"
    if [[ -z "$value" ]]; then
      value="$(sed -n "s/^${name}=//p" "$ENV_FILE" | tail -n 1)"
      value="${value%$'\r'}"
      if [[ "$value" == \"*\" && "$value" == *\" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    printf '%s' "$value"
  }

  https_domain="$(read_env_value HTTPS_DOMAIN)"
  public_base_url="$(read_env_value PUBLIC_BASE_URL)"
  https_port="$(read_env_value PUBLIC_HTTPS_PORT)"
  https_port="${https_port:-443}"
  [[ -n "$https_domain" && -n "$public_base_url" ]] || {
    echo "Error: HTTPS_DOMAIN and PUBLIC_BASE_URL are required for HTTPS verification." >&2
    exit 1
  }

  valid_https_domain() {
    local domain="$1"
    local label
    local labels=()
    [[ ${#domain} -le 253 && "$domain" == *.* ]] || return 1
    IFS='.' read -r -a labels <<< "$domain"
    ((${#labels[@]} >= 2)) || return 1
    for label in "${labels[@]}"; do
      [[ ${#label} -ge 1 && ${#label} -le 63 ]] || return 1
      [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
    done
  }
  valid_https_domain "$https_domain" || {
    echo "Error: HTTPS_DOMAIN is not a valid DNS hostname." >&2
    exit 1
  }
  [[ "$https_port" =~ ^[1-9][0-9]*$ ]] && ((https_port <= 65535)) || {
    echo "Error: PUBLIC_HTTPS_PORT must be between 1 and 65535." >&2
    exit 1
  }
  expected_base_url="https://${https_domain}"
  if [[ "$https_port" != "443" ]]; then
    expected_base_url+=":${https_port}"
  fi
  [[ "$public_base_url" == "$expected_base_url" ]] || {
    echo "Error: PUBLIC_BASE_URL does not match HTTPS_DOMAIN and PUBLIC_HTTPS_PORT." >&2
    exit 1
  }

  redirect_headers="$(mktemp)"
  trap 'rm -f "$redirect_headers"' EXIT
  redirect_status="$(curl --silent --show-error --output /dev/null \
    --dump-header "$redirect_headers" --write-out '%{http_code}' \
    --connect-timeout 5 --max-time 15 \
    --header "Host: $https_domain" "http://127.0.0.1:${public_port}/")"
  [[ "$redirect_status" == "308" ]] && \
    grep -Fqi "Location: ${public_base_url}/" "$redirect_headers" || {
    echo "Error: HTTP application traffic does not redirect to PUBLIC_BASE_URL." >&2
    exit 1
  }
  rm -f "$redirect_headers"
  trap - EXIT

  https_address="$(docker port "$proxy_container_id" 8443/tcp | sed -n '1p')"
  published_https_port="${https_address##*:}"
  [[ "$published_https_port" == "$https_port" ]] || {
    echo "Error: reverse proxy does not publish the configured HTTPS port." >&2
    exit 1
  }

  resolve_target="${https_domain}:${https_port}:127.0.0.1"
  echo "Checking HTTPS certificate hostname, HSTS, health, and application routes..."
  health_headers="$(mktemp)"
  trap 'rm -f "$health_headers"' EXIT
  curl --fail --silent --show-error --output /dev/null --dump-header "$health_headers" \
    --connect-timeout 5 --max-time 20 --resolve "$resolve_target" \
    "${public_base_url}/healthz"
  grep -Eiq '^Strict-Transport-Security:[[:space:]]*max-age=' "$health_headers" || {
    echo "Error: HTTPS response is missing Strict-Transport-Security." >&2
    exit 1
  }
  curl --fail --silent --show-error --output /dev/null \
    --connect-timeout 5 --max-time 20 --resolve "$resolve_target" \
    "${public_base_url}/"
  curl --fail --silent --show-error --output /dev/null \
    --connect-timeout 5 --max-time 20 --resolve "$resolve_target" \
    "${public_base_url}/api/health"
  rm -f "$health_headers"
  trap - EXIT
fi

echo "Production verification passed."

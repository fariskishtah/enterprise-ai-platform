#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=".env.production"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-/etc/letsencrypt}"

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

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" || "$(pwd -P)" != "$(cd "$REPO_ROOT" && pwd -P)" ]]; then
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

HTTPS_DOMAIN="$(read_env_value HTTPS_DOMAIN)"
PUBLIC_BASE_URL="$(read_env_value PUBLIC_BASE_URL)"
PUBLIC_HTTPS_PORT="$(read_env_value PUBLIC_HTTPS_PORT)"
PUBLIC_HTTPS_PORT="${PUBLIC_HTTPS_PORT:-443}"

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

[[ -n "$HTTPS_DOMAIN" ]] || {
  echo "Error: HTTPS_DOMAIN must be set in the environment or environment file." >&2
  exit 1
}
valid_https_domain "$HTTPS_DOMAIN" || {
  echo "Error: HTTPS_DOMAIN is not a valid DNS hostname." >&2
  exit 1
}
[[ "$PUBLIC_HTTPS_PORT" =~ ^[1-9][0-9]*$ ]] && \
  ((PUBLIC_HTTPS_PORT <= 65535)) || {
  echo "Error: PUBLIC_HTTPS_PORT must be between 1 and 65535." >&2
  exit 1
}

expected_base="https://${HTTPS_DOMAIN}"
if [[ "$PUBLIC_HTTPS_PORT" != "443" ]]; then
  expected_base+=":${PUBLIC_HTTPS_PORT}"
fi
[[ "$PUBLIC_BASE_URL" == "$expected_base" ]] || {
  echo "Error: PUBLIC_BASE_URL must be exactly $expected_base in HTTPS mode." >&2
  exit 1
}

certificate_dir="$LETSENCRYPT_DIR/live/$HTTPS_DOMAIN"
certificate_file="$certificate_dir/fullchain.pem"
private_key_file="$certificate_dir/privkey.pem"
[[ -f "$certificate_file" ]] || {
  echo "Error: the HTTPS certificate was not found under /etc/letsencrypt/live/HTTPS_DOMAIN/." >&2
  exit 1
}
[[ -f "$private_key_file" ]] || {
  echo "Error: the HTTPS private key was not found under /etc/letsencrypt/live/HTTPS_DOMAIN/." >&2
  exit 1
}

generated_dir="$REPO_ROOT/.deployment/https"
generated_config="$generated_dir/default.conf"
template="$REPO_ROOT/infrastructure/nginx/https.conf.template"
mkdir -p "$generated_dir"
temporary_config="$(mktemp "$generated_dir/default.conf.XXXXXX")"
trap 'rm -f "$temporary_config"' EXIT

escaped_base_url="${PUBLIC_BASE_URL//&/\\&}"
sed \
  -e "s/__HTTPS_DOMAIN__/$HTTPS_DOMAIN/g" \
  -e "s|__PUBLIC_BASE_URL__|$escaped_base_url|g" \
  "$template" > "$temporary_config"
chmod 600 "$temporary_config"

echo "Validating generated HTTPS Nginx configuration..."
docker run --rm \
  --add-host backend:127.0.0.1 \
  --add-host frontend:127.0.0.1 \
  --volume "$temporary_config:/etc/nginx/conf.d/default.conf:ro" \
  --volume "$REPO_ROOT/infrastructure/nginx/routes.inc:/etc/nginx/routes.inc:ro" \
  --volume "$LETSENCRYPT_DIR:/etc/letsencrypt:ro" \
  nginx:1.28.0-alpine nginx -t

mv "$temporary_config" "$generated_config"
trap - EXIT
echo "Generated HTTPS configuration: .deployment/https/default.conf"

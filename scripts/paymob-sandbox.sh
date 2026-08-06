#!/usr/bin/env bash
set -Eeuo pipefail

readonly PRODUCTION_PROJECT="ai-manufacturing-platform"
readonly SANDBOX_PROJECT="factorymind-paymob-sandbox"
readonly PRODUCTION_DOMAIN="factorymind.ddnsgeek.com"
readonly SANDBOX_DOMAIN="factorymind-sandbox.ddnsgeek.com"
readonly EDGE_NETWORK="factorymind-paymob-sandbox-edge"
readonly EDGE_ALIAS="factorymind-paymob-sandbox-upstream"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly ENV_FILE="$REPO_ROOT/.env.paymob-sandbox"
readonly STATE_DIR="$REPO_ROOT/.deployment/paymob-sandbox"
readonly GENERATED_NGINX="$STATE_DIR/nginx/sandbox-vhost.conf"
readonly NGINX_INCLUDE_DESTINATION="/etc/nginx/sandbox-conf.d"
readonly NGINX_MANAGED_FILENAME="paymob-sandbox.conf"
readonly NGINX_CERT_DESTINATION="/etc/nginx/paymob-sandbox-certs"
readonly INGRESS_MARKER="$STATE_DIR/ingress-active"
readonly TEMPLATE="$REPO_ROOT/infrastructure/nginx/paymob-sandbox-edge.conf.template"
readonly DOCKER_BIN="${DOCKER_BIN:-docker}"

DRY_RUN=false
CONFIRMATION=""
PRODUCTION_PROXY_ID=""
PRODUCTION_PROXY_SERVICE=""
PRODUCTION_BACKEND_ID=""
PRODUCTION_BACKEND_SERVICE=""
PRODUCTION_POSTGRES_ID=""
PRODUCTION_POSTGRES_SERVICE=""
PRODUCTION_REDIS_ID=""
PRODUCTION_REDIS_SERVICE=""

usage() {
  cat >&2 <<'EOF'
Usage: scripts/paymob-sandbox.sh ACTION [--dry-run] [--confirm TOKEN]

Read-only actions:
  dry-run            Print the deployment sequence without contacting Docker.
  labels             Discover production service labels without assuming names.
  preflight          Run read-only production and repository checks.
  status             Show sandbox Compose status.
  verify-isolation   Verify runtime separation and public health.

Local/sandbox actions:
  configure          Interactively create .env.paymob-sandbox (secrets hidden).
  start              TOKEN: START-SANDBOX
  seed               TOKEN: SEED-SANDBOX-USERS
  issue-certificate  TOKEN: ISSUE-SANDBOX-CERTIFICATE

Shared-edge/destructive actions (exact confirmation required):
  activate-ingress   TOKEN: ACTIVATE-SANDBOX-INGRESS
  refresh-certificate TOKEN: REFRESH-SANDBOX-CERTIFICATE
  deactivate-ingress TOKEN: DEACTIVATE-SANDBOX-INGRESS
  stop               TOKEN: STOP-SANDBOX
  purge-volumes      TOKEN: DELETE-SANDBOX-VOLUMES

This script never reads .env.production and never removes volumes by default.
EOF
}

quote_command() {
  local value
  printf '+'
  for value in "$@"; do
    printf ' %q' "$value"
  done
  printf '\n'
}

run() {
  if [[ "$DRY_RUN" == true ]]; then
    quote_command "$@"
    return 0
  fi
  "$@"
}

compose() {
  local command=(
    "$DOCKER_BIN" compose
    --project-name "$SANDBOX_PROJECT"
    --env-file "$ENV_FILE"
    -f "$REPO_ROOT/docker-compose.yml"
    -f "$REPO_ROOT/docker-compose.prod.yml"
    -f "$REPO_ROOT/docker-compose.staging.yml"
    -f "$REPO_ROOT/docker-compose.paymob-sandbox.yml"
  )
  run "${command[@]}" "$@"
}

require_confirmation() {
  local expected="$1"
  [[ "$CONFIRMATION" == "$expected" ]] || {
    echo "Refusing action without --confirm $expected." >&2
    exit 2
  }
}

require_repository() {
  [[ -f "$REPO_ROOT/docker-compose.paymob-sandbox.yml" && -f "$TEMPLATE" ]] || {
    echo "Sandbox deployment files are incomplete." >&2
    exit 1
  }
}

file_mode() {
  stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"
}

require_environment() {
  [[ -f "$ENV_FILE" ]] || {
    echo "Sandbox environment is not configured; run configure first." >&2
    exit 1
  }
  [[ "$(file_mode "$ENV_FILE")" == "600" ]] || {
    echo "Sandbox environment must have mode 0600." >&2
    exit 1
  }
}

read_env_value() {
  local name="$1" value
  value="$(sed -n "s/^${name}=//p" "$ENV_FILE" | tail -n 1)"
  value="${value%$'\r'}"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

docker_available() {
  local attempt process_id
  "$DOCKER_BIN" version --format '{{.Server.Version}}' >/dev/null 2>&1 &
  process_id=$!
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "$process_id" >/dev/null 2>&1; then
      if wait "$process_id"; then
        return 0
      fi
      return 1
    fi
    sleep 1
  done
  kill "$process_id" >/dev/null 2>&1 || true
  wait "$process_id" >/dev/null 2>&1 || true
  return 1
}

inspect_label() {
  "$DOCKER_BIN" inspect --format \
    "{{ index .Config.Labels \"$2\" }}" "$1"
}

inspect_mount_destinations() {
  "$DOCKER_BIN" inspect --format \
    '{{range .Mounts}}{{println .Destination}}{{end}}' "$1"
}

inspect_exposed_ports() {
  "$DOCKER_BIN" inspect --format \
    '{{range $port, $_ := .Config.ExposedPorts}}{{println $port}}{{end}}' "$1"
}

inspect_command() {
  "$DOCKER_BIN" inspect --format \
    '{{json .Config.Cmd}} {{json .Config.Entrypoint}}' "$1"
}

append_candidate() {
  local role="$1" id="$2"
  case "$role" in
    proxy) PROXY_CANDIDATES+=("$id") ;;
    backend) BACKEND_CANDIDATES+=("$id") ;;
    postgres) POSTGRES_CANDIDATES+=("$id") ;;
    redis) REDIS_CANDIDATES+=("$id") ;;
  esac
}

select_candidate() {
  local role="$1" count id service
  shift
  count=$#
  [[ "$count" -eq 1 ]] || {
    echo "Expected exactly one production $role container; found $count." >&2
    exit 1
  }
  id="$1"
  service="$(inspect_label "$id" com.docker.compose.service)"
  [[ -n "$service" ]] || {
    echo "The discovered production $role container has no Compose service label." >&2
    exit 1
  }
  case "$role" in
    reverse-proxy)
      PRODUCTION_PROXY_ID="$id"
      PRODUCTION_PROXY_SERVICE="$service"
      ;;
    backend)
      PRODUCTION_BACKEND_ID="$id"
      PRODUCTION_BACKEND_SERVICE="$service"
      ;;
    postgres)
      PRODUCTION_POSTGRES_ID="$id"
      PRODUCTION_POSTGRES_SERVICE="$service"
      ;;
    redis)
      PRODUCTION_REDIS_ID="$id"
      PRODUCTION_REDIS_SERVICE="$service"
      ;;
  esac
}

discover_production_services() {
  local id project mounts ports command
  local ids=()
  PROXY_CANDIDATES=()
  BACKEND_CANDIDATES=()
  POSTGRES_CANDIDATES=()
  REDIS_CANDIDATES=()

  while IFS= read -r id; do
    [[ -n "$id" ]] && ids+=("$id")
  done < <(
    "$DOCKER_BIN" ps -q \
      --filter "label=com.docker.compose.project=$PRODUCTION_PROJECT"
  )
  [[ "${#ids[@]}" -gt 0 ]] || {
    echo "No running containers were found for production project $PRODUCTION_PROJECT." >&2
    exit 1
  }

  for id in "${ids[@]}"; do
    project="$(inspect_label "$id" com.docker.compose.project)"
    [[ "$project" == "$PRODUCTION_PROJECT" ]] || {
      echo "A production candidate has an unexpected Compose project label." >&2
      exit 1
    }
    mounts="$(inspect_mount_destinations "$id")"
    ports="$(inspect_exposed_ports "$id")"
    command="$(inspect_command "$id")"

    if grep -Fxq '/etc/nginx/conf.d/default.conf' <<<"$mounts" &&
      grep -Fxq '/etc/nginx/routes.inc' <<<"$mounts" &&
      grep -Eq '(^|[[:space:]])8443/tcp($|[[:space:]])' <<<"$ports"; then
      append_candidate proxy "$id"
    fi
    if grep -Eq 'uvicorn' <<<"$command" &&
      grep -Eq '(^|[[:space:]])8000/tcp($|[[:space:]])' <<<"$ports"; then
      append_candidate backend "$id"
    fi
    if grep -Fxq '/var/lib/postgresql/data' <<<"$mounts" &&
      grep -Eq '(^|[[:space:]])5432/tcp($|[[:space:]])' <<<"$ports"; then
      append_candidate postgres "$id"
    fi
    if grep -Fxq '/data' <<<"$mounts" &&
      grep -Eq '(^|[[:space:]])6379/tcp($|[[:space:]])' <<<"$ports"; then
      append_candidate redis "$id"
    fi
  done

  select_candidate reverse-proxy "${PROXY_CANDIDATES[@]}"
  select_candidate backend "${BACKEND_CANDIDATES[@]}"
  select_candidate postgres "${POSTGRES_CANDIDATES[@]}"
  select_candidate redis "${REDIS_CANDIDATES[@]}"
}

print_production_labels() {
  "$DOCKER_BIN" ps \
    --filter "label=com.docker.compose.project=$PRODUCTION_PROJECT" \
    --format 'table {{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}'
  discover_production_services
  printf 'Validated role labels:\n'
  printf '  reverse-proxy: %s\n' "$PRODUCTION_PROXY_SERVICE"
  printf '  backend: %s\n' "$PRODUCTION_BACKEND_SERVICE"
  printf '  postgres: %s\n' "$PRODUCTION_POSTGRES_SERVICE"
  printf '  redis: %s\n' "$PRODUCTION_REDIS_SERVICE"
}

production_provider_is_disabled() {
  "$DOCKER_BIN" exec "$PRODUCTION_BACKEND_ID" /bin/sh -c \
    'test "$PAYMENT_PROVIDER" = disabled'
}

preflight() {
  require_repository
  docker_available || {
    echo "Docker daemon is unavailable; production labels were not inspected." >&2
    exit 1
  }
  print_production_labels
  production_provider_is_disabled || {
    echo "Production PAYMENT_PROVIDER is not confirmed disabled." >&2
    exit 1
  }
  require_managed_ingress_layout >/dev/null
  echo "Read-only preflight passed; production payment collection is disabled and the isolated ingress layout is present."
}

print_dry_run() {
  cat <<EOF
Dry run only; no Docker, certificate, environment, or ingress mutation performed.
Production project filter: com.docker.compose.project=$PRODUCTION_PROJECT
Production roles: discovered from labels plus mounts, commands, and exposed ports
Sandbox project: $SANDBOX_PROJECT
Sandbox edge network: $EDGE_NETWORK
Sandbox environment: $ENV_FILE

Planned manual sequence:
  scripts/paymob-sandbox.sh preflight
  scripts/paymob-sandbox.sh configure
  scripts/paymob-sandbox.sh start --confirm START-SANDBOX
  scripts/paymob-sandbox.sh seed --confirm SEED-SANDBOX-USERS
  scripts/paymob-sandbox.sh issue-certificate --confirm ISSUE-SANDBOX-CERTIFICATE
  scripts/paymob-sandbox.sh activate-ingress --confirm ACTIVATE-SANDBOX-INGRESS
  scripts/paymob-sandbox.sh verify-isolation

No action reads .env.production. No action removes volumes by default.
EOF
}

read_hidden() {
  local prompt="$1"
  printf '%s' "$prompt" >/dev/tty
  IFS= read -r -s HIDDEN_VALUE </dev/tty
  printf '\n' >/dev/tty
  [[ -n "$HIDDEN_VALUE" && "$HIDDEN_VALUE" != *$'\n'* && "$HIDDEN_VALUE" != *$'\r'* ]] || {
    echo "A required value was empty or invalid." >&2
    exit 1
  }
}

write_env() {
  local destination="$1" name="$2" value="$3"
  [[ "$value" != *"'"* && "$value" != *$'\n'* && "$value" != *$'\r'* ]] || {
    echo "$name contains unsupported dotenv characters." >&2
    exit 1
  }
  printf "%s='%s'\n" "$name" "$value" >>"$destination"
}

configure() {
  local next_file database_password secret_key grafana_password
  local paymob_secret paymob_public paymob_hmac paymob_integration paymob_merchant
  local letsencrypt_email
  require_repository
  command -v openssl >/dev/null 2>&1 || {
    echo "openssl is required." >&2
    exit 1
  }
  if [[ -e "$ENV_FILE" ]]; then
    require_confirmation REPLACE-SANDBOX-ENV
  fi
  umask 077
  database_password="$(openssl rand -hex 32)"
  secret_key="$(openssl rand -hex 48)"
  grafana_password="$(openssl rand -hex 32)"

  read_hidden "Paymob sandbox Secret Key: "
  paymob_secret="$HIDDEN_VALUE"
  read_hidden "Paymob sandbox Public Key: "
  paymob_public="$HIDDEN_VALUE"
  read_hidden "Paymob sandbox HMAC Secret: "
  paymob_hmac="$HIDDEN_VALUE"
  read_hidden "Paymob sandbox Integration ID: "
  paymob_integration="$HIDDEN_VALUE"
  read_hidden "Paymob sandbox Merchant Owner ID: "
  paymob_merchant="$HIDDEN_VALUE"
  read_hidden "Let's Encrypt account email: "
  letsencrypt_email="$HIDDEN_VALUE"
  unset HIDDEN_VALUE

  [[ "$paymob_integration" =~ ^[1-9][0-9]*$ && "$paymob_merchant" =~ ^[1-9][0-9]*$ ]] || {
    echo "Paymob integration and merchant identifiers must be positive integers." >&2
    exit 1
  }
  [[ "$paymob_secret" != sk_live_* && "$paymob_public" != pk_live_* ]] || {
    echo "Live Paymob key prefixes are forbidden in the sandbox." >&2
    exit 1
  }

  next_file="$ENV_FILE.next"
  : >"$next_file"
  trap 'rm -f -- "$next_file"' EXIT
  write_env "$next_file" POSTGRES_DB factorymind_paymob_sandbox
  write_env "$next_file" POSTGRES_USER factorymind_paymob_sandbox
  write_env "$next_file" POSTGRES_PASSWORD "$database_password"
  write_env "$next_file" DATABASE_URL "postgresql+psycopg://factorymind_paymob_sandbox:${database_password}@postgres:5432/factorymind_paymob_sandbox"
  write_env "$next_file" REDIS_URL redis://redis:6379/0
  write_env "$next_file" SECRET_KEY "$secret_key"
  write_env "$next_file" JWT_ISSUER factorymind-paymob-sandbox
  write_env "$next_file" JWT_AUDIENCE factorymind-paymob-sandbox-browser
  write_env "$next_file" JWT_ALGORITHM HS256
  write_env "$next_file" ENVIRONMENT staging
  write_env "$next_file" APP_ENV staging
  write_env "$next_file" APP_PUBLIC_URL "https://$SANDBOX_DOMAIN"
  write_env "$next_file" API_BASE_URL "https://$SANDBOX_DOMAIN/api"
  write_env "$next_file" ALLOWED_HOSTS "[\"$SANDBOX_DOMAIN\"]"
  write_env "$next_file" CORS_ALLOWED_ORIGINS "[\"https://$SANDBOX_DOMAIN\"]"
  write_env "$next_file" CORS_ALLOW_CREDENTIALS true
  write_env "$next_file" COOKIE_SECURE true
  write_env "$next_file" COOKIE_SAMESITE lax
  write_env "$next_file" COOKIE_DOMAIN ""
  write_env "$next_file" TRUSTED_PROXY_IPS "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
  write_env "$next_file" ENABLE_API_DOCS false
  write_env "$next_file" DEMO_TOOLS_ENABLED false
  write_env "$next_file" EMAIL_PROVIDER disabled
  write_env "$next_file" EMAIL_FROM_ADDRESS sandbox-no-reply@factorymind.ddnsgeek.com
  write_env "$next_file" SUPPORT_NOTIFICATION_EMAIL sandbox-support@factorymind.ddnsgeek.com
  write_env "$next_file" GRAFANA_ADMIN_USER factorymind-sandbox
  write_env "$next_file" GRAFANA_ADMIN_PASSWORD "$grafana_password"
  write_env "$next_file" PAYMENT_PROVIDER paymob
  write_env "$next_file" PAYMENT_SANDBOX_MODE true
  write_env "$next_file" PAYMENT_CURRENCY EGP
  write_env "$next_file" PAYMOB_SECRET_KEY "$paymob_secret"
  write_env "$next_file" PAYMOB_PUBLIC_KEY "$paymob_public"
  write_env "$next_file" PAYMOB_HMAC_SECRET "$paymob_hmac"
  write_env "$next_file" PAYMOB_INTEGRATION_ID "$paymob_integration"
  write_env "$next_file" PAYMOB_MERCHANT_ID "$paymob_merchant"
  write_env "$next_file" PAYMOB_BASE_URL https://accept.paymob.com
  write_env "$next_file" PAYMOB_WEBHOOK_URL "https://$SANDBOX_DOMAIN/api/billing/webhooks/paymob"
  write_env "$next_file" PAYMENT_SUCCESS_URL "https://$SANDBOX_DOMAIN/settings/billing/return"
  write_env "$next_file" PAYMENT_FAILURE_URL "https://$SANDBOX_DOMAIN/settings/billing/return"
  write_env "$next_file" PAYMOB_ALLOWED_CHECKOUT_HOSTS '["accept.paymob.com"]'
  write_env "$next_file" PAYMOB_SUPPORTED_SOURCE_TYPES '["card"]'
  write_env "$next_file" PAYMENT_HTTP_TIMEOUT_SECONDS 10
  write_env "$next_file" BILLING_COMMERCIAL_MODEL prepaid_manual_renewal
  write_env "$next_file" BILLING_CHECKOUT_EXPIRY_MINUTES 30
  write_env "$next_file" BILLING_RETURN_REFERENCE_EXPIRY_MINUTES 60
  write_env "$next_file" BILLING_ENTITLEMENTS_ENFORCED true
  write_env "$next_file" BILLING_WEBHOOK_QUEUE_NAME factorymind-sandbox-billing-webhooks
  write_env "$next_file" BILLING_WEBHOOK_MAX_RETRIES 5
  write_env "$next_file" BILLING_WEBHOOK_RETRY_BASE_SECONDS 30
  write_env "$next_file" BILLING_WEBHOOK_QUEUED_STALE_SECONDS 300
  write_env "$next_file" BILLING_WEBHOOK_PROCESSING_STALE_SECONDS 300
  write_env "$next_file" BILLING_WEBHOOK_RECOVERY_BATCH_SIZE 100
  write_env "$next_file" BILLING_WEBHOOK_RECOVERY_SCHEDULING_ENABLED true
  write_env "$next_file" BILLING_WEBHOOK_RECOVERY_INTERVAL_SECONDS 60
  write_env "$next_file" BILLING_GRACE_PERIOD_DAYS 7
  write_env "$next_file" BILLING_INCOMPLETE_EXPIRY_HOURS 24
  write_env "$next_file" BILLING_SUSPENSION_EXPIRY_DAYS 30
  write_env "$next_file" BILLING_LIFECYCLE_RECONCILIATION_BATCH_SIZE 100
  write_env "$next_file" BILLING_LIFECYCLE_RECONCILIATION_SCHEDULING_ENABLED true
  write_env "$next_file" BILLING_LIFECYCLE_RECONCILIATION_INTERVAL_SECONDS 60
  write_env "$next_file" EMAIL_QUEUE_NAME factorymind-sandbox-transactional-email
  write_env "$next_file" TRAINING_QUEUE_NAME factorymind-sandbox-ai-training
  write_env "$next_file" DATASET_QUEUE_NAME factorymind-sandbox-datasets
  write_env "$next_file" RAG_QUEUE_NAME factorymind-sandbox-rag
  write_env "$next_file" MONITORING_QUEUE_NAME factorymind-sandbox-ai-monitoring
  write_env "$next_file" HTTPS_DOMAIN "$SANDBOX_DOMAIN"
  write_env "$next_file" PUBLIC_BASE_URL "https://$SANDBOX_DOMAIN"
  write_env "$next_file" LETSENCRYPT_ACCOUNT_EMAIL "$letsencrypt_email"
  chmod 600 "$next_file"
  mv -f -- "$next_file" "$ENV_FILE"
  trap - EXIT
  unset database_password secret_key grafana_password paymob_secret paymob_public
  unset paymob_hmac paymob_integration paymob_merchant letsencrypt_email
  echo "Sandbox environment created without displaying secret values."
}

ensure_edge_network() {
  if "$DOCKER_BIN" network inspect "$EDGE_NETWORK" >/dev/null 2>&1; then
    local label
    label="$("$DOCKER_BIN" network inspect --format \
      '{{ index .Labels "com.factorymind.environment" }}' "$EDGE_NETWORK")"
    [[ "$label" == paymob-sandbox ]] || {
      echo "Existing edge network is not owned by the Paymob sandbox." >&2
      exit 1
    }
    return 0
  fi
  run "$DOCKER_BIN" network create --driver bridge \
    --label com.factorymind.environment=paymob-sandbox "$EDGE_NETWORK"
}

start_sandbox() {
  require_confirmation START-SANDBOX
  require_environment
  preflight
  ensure_edge_network
  compose config --quiet
  compose pull --ignore-buildable
  compose build --pull
  compose up --detach --no-build --wait postgres redis
  compose run --rm --no-deps backend alembic upgrade head
  compose run --rm --no-deps backend alembic check
  compose up --detach --no-build --wait \
    backend training-worker frontend reverse-proxy
  echo "Sandbox services started without activating shared ingress."
}

seed_sandbox() {
  local owner_email owner_password external_email external_password
  require_confirmation SEED-SANDBOX-USERS
  require_environment
  if [[ "$DRY_RUN" == true ]]; then
    quote_command scripts/paymob-sandbox.sh seed-with-hidden-environment
    return 0
  fi
  read_hidden "Sandbox Owner email: "
  owner_email="$HIDDEN_VALUE"
  read_hidden "Sandbox Owner password: "
  owner_password="$HIDDEN_VALUE"
  read_hidden "Cross-tenant Owner email: "
  external_email="$HIDDEN_VALUE"
  read_hidden "Cross-tenant Owner password: "
  external_password="$HIDDEN_VALUE"
  unset HIDDEN_VALUE
  export PAYMOB_SANDBOX_OWNER_EMAIL="$owner_email"
  export PAYMOB_SANDBOX_OWNER_PASSWORD="$owner_password"
  export PAYMOB_SANDBOX_EXTERNAL_OWNER_EMAIL="$external_email"
  export PAYMOB_SANDBOX_EXTERNAL_OWNER_PASSWORD="$external_password"
  compose exec -T \
    -e ENABLE_DEVELOPMENT_SEED=true \
    -e PAYMOB_SANDBOX_OWNER_EMAIL \
    -e PAYMOB_SANDBOX_OWNER_PASSWORD \
    -e PAYMOB_SANDBOX_EXTERNAL_OWNER_EMAIL \
    -e PAYMOB_SANDBOX_EXTERNAL_OWNER_PASSWORD \
    backend python - <"$REPO_ROOT/scripts/seed_paymob_sandbox_users.py"
  unset owner_email owner_password external_email external_password
  unset PAYMOB_SANDBOX_OWNER_EMAIL PAYMOB_SANDBOX_OWNER_PASSWORD
  unset PAYMOB_SANDBOX_EXTERNAL_OWNER_EMAIL PAYMOB_SANDBOX_EXTERNAL_OWNER_PASSWORD
}

mount_source_for_destination() {
  local container_id="$1" destination="$2"
  "$DOCKER_BIN" inspect --format \
    "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{println .Source}}{{end}}{{end}}" \
    "$container_id" | sed '/^[[:space:]]*$/d'
}

stage_sandbox_certificate() {
  local live_dir="$1" target_dir="$STATE_DIR/https/certs"
  if [[ "$DRY_RUN" == true ]]; then
    quote_command stage-certificate-without-printing-private-key "$live_dir" "$target_dir"
    return 0
  fi
  sudo test -f "$live_dir/fullchain.pem" && sudo test -f "$live_dir/privkey.pem" || {
    echo "The sandbox certificate is incomplete." >&2
    exit 1
  }
  run install -d -m 750 "$target_dir"
  run sudo install -o 101 -g 101 -m 0640 \
    "$live_dir/fullchain.pem" "$target_dir/fullchain.pem"
  run sudo install -o 101 -g 101 -m 0640 \
    "$live_dir/privkey.pem" "$target_dir/privkey.pem"
}

issue_certificate() {
  local webroot letsencrypt_email
  require_confirmation ISSUE-SANDBOX-CERTIFICATE
  require_environment
  preflight
  webroot="$(mount_source_for_destination "$PRODUCTION_PROXY_ID" /var/www/certbot)"
  [[ -n "$webroot" && -d "$webroot" ]] || {
    echo "The production ACME webroot mount could not be validated." >&2
    exit 1
  }
  letsencrypt_email="$(read_env_value LETSENCRYPT_ACCOUNT_EMAIL)"
  [[ -n "$letsencrypt_email" ]] || {
    echo "LETSENCRYPT_ACCOUNT_EMAIL is required in the sandbox environment." >&2
    exit 1
  }
  run sudo certbot certonly --non-interactive --agree-tos --no-eff-email \
    --webroot --webroot-path "$webroot" \
    --cert-name "$SANDBOX_DOMAIN" --domain "$SANDBOX_DOMAIN" \
    --email "$letsencrypt_email"
  stage_sandbox_certificate "/etc/letsencrypt/live/$SANDBOX_DOMAIN"
  echo "Sandbox certificate staged; shared ingress was not activated."
}

sandbox_proxy_id() {
  local ids=() id label
  while IFS= read -r id; do
    [[ -n "$id" ]] && ids+=("$id")
  done < <(
    "$DOCKER_BIN" ps -q \
      --filter "label=com.docker.compose.project=$SANDBOX_PROJECT" \
      --filter label=com.factorymind.ingress-role=sandbox-upstream
  )
  [[ "${#ids[@]}" -eq 1 ]] || {
    echo "Expected exactly one labeled sandbox ingress container." >&2
    exit 1
  }
  label="$(inspect_label "${ids[0]}" com.docker.compose.project)"
  [[ "$label" == "$SANDBOX_PROJECT" ]] || exit 1
  printf '%s' "${ids[0]}"
}

sandbox_service_id() {
  local service="$1" ids=() id
  while IFS= read -r id; do
    [[ -n "$id" ]] && ids+=("$id")
  done < <(
    "$DOCKER_BIN" ps -q \
      --filter "label=com.docker.compose.project=$SANDBOX_PROJECT" \
      --filter "label=com.docker.compose.service=$service"
  )
  [[ "${#ids[@]}" -eq 1 ]] || {
    echo "Expected exactly one running Sandbox $service container." >&2
    exit 1
  }
  [[ "$(inspect_label "${ids[0]}" com.docker.compose.project)" == "$SANDBOX_PROJECT" ]] || {
    echo "A Sandbox container has an unexpected project label." >&2
    exit 1
  }
  [[ "$(inspect_label "${ids[0]}" com.factorymind.environment)" == paymob-sandbox ]] || {
    echo "A Sandbox container lacks the required ownership label." >&2
    exit 1
  }
  printf '%s' "${ids[0]}"
}

inspect_environment_value() {
  local container_id="$1" variable="$2"
  "$DOCKER_BIN" inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
    "$container_id" | sed -n "s/^${variable}=//p" | tail -n 1
}

container_network_ids() {
  "$DOCKER_BIN" inspect --format \
    '{{range $name, $network := .NetworkSettings.Networks}}{{println $network.NetworkID}}{{end}}' \
    "$1" | sed '/^[[:space:]]*$/d' | sort -u
}

assert_no_shared_networks() {
  local left="$1" right="$2"
  [[ -z "$(comm -12 <(container_network_ids "$left") <(container_network_ids "$right"))" ]] || {
    echo "Production and Sandbox data-plane containers share a Docker network." >&2
    exit 1
  }
}

assert_proxy_network_boundary() {
  local production_proxy="$1" sandbox_proxy="$2" edge_id shared_ids
  edge_id="$("$DOCKER_BIN" network inspect --format '{{.Id}}' "$EDGE_NETWORK")"
  [[ -n "$edge_id" ]] || {
    echo "The controlled edge network has no inspectable ID." >&2
    exit 1
  }
  shared_ids="$(comm -12 \
    <(container_network_ids "$production_proxy") \
    <(container_network_ids "$sandbox_proxy"))"
  if [[ -e "$INGRESS_MARKER" ]]; then
    [[ "$shared_ids" == "$edge_id" ]] || {
      echo "The reverse proxies do not share exactly the controlled edge network." >&2
      exit 1
    }
  else
    [[ -z "$shared_ids" ]] || {
      echo "Inactive Sandbox ingress still shares a network with production." >&2
      exit 1
    }
  fi
}

assert_distinct_environment_value() {
  local production_container="$1" sandbox_container="$2" variable="$3"
  local production_value sandbox_value
  production_value="$(inspect_environment_value "$production_container" "$variable")"
  sandbox_value="$(inspect_environment_value "$sandbox_container" "$variable")"
  [[ -n "$production_value" && -n "$sandbox_value" && "$production_value" != "$sandbox_value" ]] || {
    echo "Production and Sandbox must have distinct $variable values." >&2
    exit 1
  }
}

assert_host_port_owner() {
  local port="$1" expected_container="$2" owners=() id
  while IFS= read -r id; do
    [[ -n "$id" ]] && owners+=("$id")
  done < <("$DOCKER_BIN" ps -q --filter "publish=$port")
  [[ "${#owners[@]}" -eq 1 && "${owners[0]}" == "$expected_container" ]] || {
    echo "Production reverse proxy is not the sole owner of host port $port." >&2
    exit 1
  }
}

render_nginx() {
  mkdir -p "$STATE_DIR/nginx"
  sed \
    -e "s/__SANDBOX_DOMAIN__/$SANDBOX_DOMAIN/g" \
    "$TEMPLATE" >"$GENERATED_NGINX.next"
  chmod 0644 "$GENERATED_NGINX.next"
  mv -f -- "$GENERATED_NGINX.next" "$GENERATED_NGINX"
}

require_managed_ingress_layout() {
  local config_mount_source certificate_mount_source
  config_mount_source="$(mount_source_for_destination \
    "$PRODUCTION_PROXY_ID" "$NGINX_INCLUDE_DESTINATION")"
  certificate_mount_source="$(mount_source_for_destination \
    "$PRODUCTION_PROXY_ID" "$NGINX_CERT_DESTINATION")"
  [[ -d "$config_mount_source" && -d "$certificate_mount_source" ]] || {
    echo "The production proxy lacks the dedicated Sandbox ingress mounts." >&2
    exit 1
  }
  "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" /bin/sh -c \
    'test -d /etc/nginx/sandbox-conf.d && test -d /etc/nginx/paymob-sandbox-certs && grep -Fqx "include /etc/nginx/sandbox-conf.d/*.conf;" /etc/nginx/conf.d/default.conf' || {
    echo "The active production Nginx layout does not support isolated includes." >&2
    exit 1
  }
  printf '%s\n%s\n' "$config_mount_source" "$certificate_mount_source"
}

network_contains_container() {
  local network="$1" container_id="$2"
  "$DOCKER_BIN" inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
    "$container_id" | grep -Fxq "$network"
}

activate_ingress() {
  local config_mount_source certificate_mount_source managed_config sandbox_proxy
  local connected_here=false installed_here=false rollback_required=false
  local ingress_mounts=()
  require_confirmation ACTIVATE-SANDBOX-INGRESS
  require_environment
  [[ -f "$STATE_DIR/https/certs/fullchain.pem" && -f "$STATE_DIR/https/certs/privkey.pem" ]] || {
    echo "Issue and stage the sandbox certificate before ingress activation." >&2
    exit 1
  }
  preflight
  sandbox_proxy="$(sandbox_proxy_id)"
  ensure_edge_network
  mapfile -t ingress_mounts < <(require_managed_ingress_layout)
  [[ "${#ingress_mounts[@]}" -eq 2 ]] || exit 1
  config_mount_source="${ingress_mounts[0]}"
  certificate_mount_source="${ingress_mounts[1]}"
  managed_config="$config_mount_source/$NGINX_MANAGED_FILENAME"
  [[ "$(cd "$certificate_mount_source" && pwd -P)" == \
    "$(cd "$STATE_DIR/https/certs" && pwd -P)" ]] || {
    echo "The Sandbox certificate mount does not resolve to the managed state directory." >&2
    exit 1
  }
  render_nginx
  if [[ -e "$INGRESS_MARKER" ]]; then
    [[ -f "$managed_config" ]] && cmp -s "$GENERATED_NGINX" "$managed_config" || {
      echo "Ingress is marked active but the managed Sandbox include differs." >&2
      exit 1
    }
    network_contains_container "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID" &&
      network_contains_container "$EDGE_NETWORK" "$sandbox_proxy" || {
      echo "Ingress is marked active but edge membership is incomplete." >&2
      exit 1
    }
    "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -t
    echo "Sandbox ingress is already active with the approved managed include."
    return 0
  fi
  [[ ! -e "$managed_config" ]] || {
    echo "An unmanaged Sandbox include exists without an activation marker." >&2
    exit 1
  }
  if [[ "$DRY_RUN" == true ]]; then
    quote_command docker-network-connect "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID"
    quote_command install-managed-nginx-include "$GENERATED_NGINX" "$managed_config"
    quote_command validate-and-reload-production-nginx-without-replacing-default
    return 0
  fi

  rollback_required=true
  rollback_activation() {
    if [[ "$rollback_required" == true ]]; then
      if [[ "$installed_here" == true ]]; then
        sudo rm -f -- "$managed_config" "$managed_config.next"
      fi
      "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -t >/dev/null 2>&1 || true
      "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -s reload >/dev/null 2>&1 || true
      if [[ "$connected_here" == true ]] &&
        network_contains_container "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID"; then
        "$DOCKER_BIN" network disconnect \
          "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID" >/dev/null 2>&1 || true
      fi
    fi
  }
  trap rollback_activation ERR

  if ! network_contains_container "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID"; then
    "$DOCKER_BIN" network connect "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID"
    connected_here=true
  fi
  network_contains_container "$EDGE_NETWORK" "$sandbox_proxy" || {
    echo "Sandbox ingress is not attached to the controlled edge network." >&2
    false
  }
  sudo install -m 0644 "$GENERATED_NGINX" "$managed_config.next"
  sudo mv -- "$managed_config.next" "$managed_config"
  installed_here=true
  "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -t
  "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -s reload
  : >"$INGRESS_MARKER"
  rollback_required=false
  trap - ERR
  echo "Sandbox ingress activated; production application services were not restarted."
}

refresh_certificate() {
  local rollback_required=false
  local certificate_backup="$STATE_DIR/https/certificate-backup.$(date -u +%Y%m%dT%H%M%SZ)"
  require_confirmation REFRESH-SANDBOX-CERTIFICATE
  [[ -e "$INGRESS_MARKER" ]] || {
    echo "Sandbox ingress is not active." >&2
    exit 1
  }
  preflight
  require_managed_ingress_layout >/dev/null
  run install -d -m 0700 "$certificate_backup"
  run sudo cp -p -- "$STATE_DIR/https/certs/fullchain.pem" \
    "$certificate_backup/fullchain.pem"
  run sudo cp -p -- "$STATE_DIR/https/certs/privkey.pem" \
    "$certificate_backup/privkey.pem"
  rollback_required=true
  rollback_certificate_refresh() {
    if [[ "$rollback_required" == true ]]; then
      sudo install -o 101 -g 101 -m 0640 \
        "$certificate_backup/fullchain.pem" \
        "$STATE_DIR/https/certs/fullchain.pem" >/dev/null 2>&1 || true
      sudo install -o 101 -g 101 -m 0640 \
        "$certificate_backup/privkey.pem" \
        "$STATE_DIR/https/certs/privkey.pem" >/dev/null 2>&1 || true
      "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -t >/dev/null 2>&1 || true
      "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -s reload >/dev/null 2>&1 || true
    fi
  }
  trap rollback_certificate_refresh ERR
  stage_sandbox_certificate "/etc/letsencrypt/live/$SANDBOX_DOMAIN"
  run "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -t
  run "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -s reload
  rollback_required=false
  trap - ERR
  echo "Sandbox certificate refreshed; the prior pair remains in the managed backup directory."
}

deactivate_ingress() {
  local archived_config config_mount_source managed_config rollback_required=false
  local ingress_mounts=()
  require_confirmation DEACTIVATE-SANDBOX-INGRESS
  preflight
  mapfile -t ingress_mounts < <(require_managed_ingress_layout)
  [[ "${#ingress_mounts[@]}" -eq 2 ]] || exit 1
  config_mount_source="${ingress_mounts[0]}"
  managed_config="$config_mount_source/$NGINX_MANAGED_FILENAME"
  if [[ ! -e "$INGRESS_MARKER" && ! -e "$managed_config" ]]; then
    echo "Sandbox ingress is already inactive."
    return 0
  fi
  [[ -e "$INGRESS_MARKER" && -f "$managed_config" ]] || {
    echo "Sandbox ingress marker and managed include are inconsistent." >&2
    exit 1
  }
  archived_config="$STATE_DIR/nginx/sandbox-vhost.deactivated.$(date -u +%Y%m%dT%H%M%SZ).disabled"
  if [[ "$DRY_RUN" == true ]]; then
    quote_command remove-only-managed-nginx-include "$managed_config"
    quote_command validate-and-reload-production-nginx
    return 0
  fi
  cp -p -- "$managed_config" "$archived_config"
  rollback_required=true
  rollback_deactivation() {
    if [[ "$rollback_required" == true && -f "$archived_config" ]]; then
      sudo install -m 0644 "$archived_config" "$managed_config"
      "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -t >/dev/null 2>&1 || true
      "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -s reload >/dev/null 2>&1 || true
    fi
  }
  trap rollback_deactivation ERR
  sudo rm -- "$managed_config"
  "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -t
  "$DOCKER_BIN" exec "$PRODUCTION_PROXY_ID" nginx -s reload
  if network_contains_container "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID"; then
    "$DOCKER_BIN" network disconnect "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID"
  fi
  rm -f -- "$INGRESS_MARKER"
  rollback_required=false
  trap - ERR
  echo "Sandbox Nginx include removed; production configuration was untouched."
}

status() {
  require_environment
  compose ps
}

verify_isolation() {
  local sandbox_backend sandbox_postgres sandbox_proxy sandbox_redis
  local production_postgres_volume production_redis_volume
  local sandbox_postgres_volume sandbox_redis_volume variable sandbox_queue
  preflight
  sandbox_backend="$(sandbox_service_id backend)"
  sandbox_postgres="$(sandbox_service_id postgres)"
  sandbox_redis="$(sandbox_service_id redis)"
  sandbox_proxy="$(sandbox_service_id reverse-proxy)"
  "$DOCKER_BIN" exec "$sandbox_backend" /bin/sh -c \
    'test "$PAYMENT_PROVIDER" = paymob && test "$PAYMENT_SANDBOX_MODE" = true && test "$ENVIRONMENT" = staging'
  [[ -z "$("$DOCKER_BIN" port "$sandbox_backend")" ]]
  [[ -z "$("$DOCKER_BIN" port "$sandbox_postgres")" ]]
  [[ -z "$("$DOCKER_BIN" port "$sandbox_redis")" ]]
  [[ -z "$("$DOCKER_BIN" port "$sandbox_proxy")" ]]

  production_postgres_volume="$(mount_source_for_destination "$PRODUCTION_POSTGRES_ID" /var/lib/postgresql/data)"
  sandbox_postgres_volume="$(mount_source_for_destination "$sandbox_postgres" /var/lib/postgresql/data)"
  production_redis_volume="$(mount_source_for_destination "$PRODUCTION_REDIS_ID" /data)"
  sandbox_redis_volume="$(mount_source_for_destination "$sandbox_redis" /data)"
  [[ -n "$production_postgres_volume" && -n "$sandbox_postgres_volume" && \
    "$production_postgres_volume" != "$sandbox_postgres_volume" ]] || {
    echo "Production and Sandbox PostgreSQL storage is not isolated." >&2
    exit 1
  }
  [[ -n "$production_redis_volume" && -n "$sandbox_redis_volume" && \
    "$production_redis_volume" != "$sandbox_redis_volume" ]] || {
    echo "Production and Sandbox Redis storage is not isolated." >&2
    exit 1
  }

  assert_distinct_environment_value "$PRODUCTION_POSTGRES_ID" "$sandbox_postgres" POSTGRES_DB
  assert_distinct_environment_value "$PRODUCTION_POSTGRES_ID" "$sandbox_postgres" POSTGRES_USER
  assert_distinct_environment_value "$PRODUCTION_POSTGRES_ID" "$sandbox_postgres" POSTGRES_PASSWORD
  assert_distinct_environment_value "$PRODUCTION_BACKEND_ID" "$sandbox_backend" DATABASE_URL
  assert_distinct_environment_value "$PRODUCTION_BACKEND_ID" "$sandbox_backend" REDIS_URL
  assert_distinct_environment_value "$PRODUCTION_BACKEND_ID" "$sandbox_backend" SECRET_KEY
  for variable in \
    BILLING_WEBHOOK_QUEUE_NAME EMAIL_QUEUE_NAME TRAINING_QUEUE_NAME \
    DATASET_QUEUE_NAME RAG_QUEUE_NAME MONITORING_QUEUE_NAME; do
    assert_distinct_environment_value \
      "$PRODUCTION_BACKEND_ID" "$sandbox_backend" "$variable"
    sandbox_queue="$(inspect_environment_value "$sandbox_backend" "$variable")"
    [[ "$sandbox_queue" == factorymind-sandbox-* ]] || {
      echo "Sandbox queue $variable lacks the required namespace." >&2
      exit 1
    }
  done

  for sandbox_container in "$sandbox_backend" "$sandbox_postgres" "$sandbox_redis"; do
    assert_no_shared_networks "$PRODUCTION_PROXY_ID" "$sandbox_container"
    assert_no_shared_networks "$PRODUCTION_BACKEND_ID" "$sandbox_container"
    assert_no_shared_networks "$PRODUCTION_POSTGRES_ID" "$sandbox_container"
    assert_no_shared_networks "$PRODUCTION_REDIS_ID" "$sandbox_container"
    network_contains_container "$EDGE_NETWORK" "$sandbox_container" && {
      echo "A Sandbox data-plane container is attached to the shared edge." >&2
      exit 1
    }
  done
  for production_container in \
    "$PRODUCTION_BACKEND_ID" "$PRODUCTION_POSTGRES_ID" "$PRODUCTION_REDIS_ID"; do
    assert_no_shared_networks "$production_container" "$sandbox_proxy"
  done
  network_contains_container "$EDGE_NETWORK" "$sandbox_proxy" || {
    echo "The Sandbox reverse proxy is not attached to its controlled edge." >&2
    exit 1
  }
  assert_proxy_network_boundary "$PRODUCTION_PROXY_ID" "$sandbox_proxy"
  assert_host_port_owner 80 "$PRODUCTION_PROXY_ID"
  assert_host_port_owner 443 "$PRODUCTION_PROXY_ID"
  curl --fail --silent --show-error "https://$PRODUCTION_DOMAIN/healthz" >/dev/null
  if [[ -e "$INGRESS_MARKER" ]]; then
    require_managed_ingress_layout >/dev/null
    network_contains_container "$EDGE_NETWORK" "$PRODUCTION_PROXY_ID" || {
      echo "Active ingress lacks production proxy edge membership." >&2
      exit 1
    }
    curl --fail --silent --show-error "https://$SANDBOX_DOMAIN/healthz" >/dev/null
    [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' \
      "https://$SANDBOX_DOMAIN/api/metrics")" == 404 ]]
  fi
  echo "Sandbox isolation checks passed."
}

stop_sandbox() {
  require_confirmation STOP-SANDBOX
  require_environment
  [[ ! -e "$INGRESS_MARKER" ]] || {
    echo "Deactivate shared ingress before stopping the sandbox." >&2
    exit 1
  }
  compose stop reverse-proxy frontend training-worker backend migrate redis postgres
  compose rm --force reverse-proxy frontend training-worker backend migrate redis postgres
  echo "Sandbox containers removed; networks and volumes retained."
}

purge_volumes() {
  local id label project volume count=0
  require_confirmation DELETE-SANDBOX-VOLUMES
  [[ ! -e "$INGRESS_MARKER" ]] || {
    echo "Deactivate shared ingress before volume cleanup." >&2
    exit 1
  }
  [[ -z "$("$DOCKER_BIN" ps -aq --filter "label=com.docker.compose.project=$SANDBOX_PROJECT")" ]] || {
    echo "Remove all sandbox containers before volume cleanup." >&2
    exit 1
  }
  while IFS= read -r volume; do
    [[ -n "$volume" ]] || continue
    project="$("$DOCKER_BIN" volume inspect --format \
      '{{ index .Labels "com.docker.compose.project" }}' "$volume")"
    label="$("$DOCKER_BIN" volume inspect --format \
      '{{ index .Labels "com.factorymind.environment" }}' "$volume")"
    [[ "$project" == "$SANDBOX_PROJECT" && "$label" == paymob-sandbox ]] || {
      echo "Refusing to remove an unowned volume." >&2
      exit 1
    }
    run "$DOCKER_BIN" volume rm -- "$volume"
    count=$((count + 1))
  done < <(
    "$DOCKER_BIN" volume ls -q \
      --filter "label=com.docker.compose.project=$SANDBOX_PROJECT" \
      --filter label=com.factorymind.environment=paymob-sandbox
  )
  echo "$count explicitly owned sandbox volumes selected for removal."
}

action="${1:-}"
[[ -n "$action" ]] || { usage; exit 2; }
shift
while (($#)); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --confirm)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      CONFIRMATION="$2"
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

case "$action" in
  dry-run) print_dry_run ;;
  labels) preflight ;;
  preflight) preflight ;;
  configure) configure ;;
  start) start_sandbox ;;
  seed) seed_sandbox ;;
  issue-certificate) issue_certificate ;;
  activate-ingress) activate_ingress ;;
  refresh-certificate) refresh_certificate ;;
  deactivate-ingress) deactivate_ingress ;;
  status) status ;;
  verify-isolation) verify_isolation ;;
  stop) stop_sandbox ;;
  purge-volumes) purge_volumes ;;
  *) usage; exit 2 ;;
esac

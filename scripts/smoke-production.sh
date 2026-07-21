#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${BASE_URL:-}"
API_BASE_URL="${API_BASE_URL:-${BASE_URL%/}/api}"
SMOKE_DOCS_EXPECTED_STATUS="${SMOKE_DOCS_EXPECTED_STATUS:-404}"
SMOKE_ENABLE_PREDICTION="${SMOKE_ENABLE_PREDICTION:-false}"

if [[ -z "$BASE_URL" || -z "${SMOKE_EMAIL:-}" || -z "${SMOKE_PASSWORD:-}" ]]; then
  echo "Usage: BASE_URL=https://staging.example SMOKE_EMAIL=... SMOKE_PASSWORD=... $0" >&2
  exit 2
fi
if [[ "$BASE_URL" != https://* && "${SMOKE_ALLOW_HTTP:-false}" != "true" ]]; then
  echo "Refusing a non-HTTPS target. Set SMOKE_ALLOW_HTTP=true only for local verification." >&2
  exit 2
fi
for command in curl python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "$command is required." >&2
    exit 2
  }
done

work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
response_file="$work_dir/response.json"

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; exit 1; }
request_status() {
  curl --silent --show-error --output "$response_file" --write-out '%{http_code}' \
    --connect-timeout 5 --max-time 20 "$@"
}
json_field() {
  python3 - "$1" "$response_file" <<'PY'
import json
import sys

field, path = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    value = json.load(stream)
for part in field.split("."):
    value = value[part]
if not isinstance(value, (str, int, float, bool)):
    raise SystemExit("field is not a scalar")
print(value)
PY
}

status="$(request_status "$API_BASE_URL/health")"
[[ "$status" == "200" ]] || fail "/health returned $status"
pass "/health"

status="$(request_status "$API_BASE_URL/ready")"
[[ "$status" == "200" ]] || fail "/ready returned $status"
pass "/ready"

status="$(request_status "$API_BASE_URL/docs")"
[[ "$status" == "$SMOKE_DOCS_EXPECTED_STATUS" ]] || \
  fail "/docs returned $status; expected $SMOKE_DOCS_EXPECTED_STATUS"
pass "/docs expected status"

login_payload="$(python3 - <<'PY'
import json
import os
print(json.dumps({"email": os.environ["SMOKE_EMAIL"], "password": os.environ["SMOKE_PASSWORD"]}))
PY
)"
status="$(request_status --header 'Content-Type: application/json' \
  --data "$login_payload" "$API_BASE_URL/auth/login")"
[[ "$status" == "200" ]] || fail "login returned $status"
access_token="$(json_field access_token)" || fail "login response omitted access_token"
refresh_token="$(json_field refresh_token)" || fail "login response omitted refresh_token"
pass "login"

status="$(request_status --header "Authorization: Bearer $access_token" "$API_BASE_URL/users/me")"
[[ "$status" == "200" ]] || fail "/users/me returned $status"
pass "/users/me"

status="$(request_status --header "Authorization: Bearer $access_token" \
  "$API_BASE_URL/factories?limit=1&offset=0")"
[[ "$status" == "200" ]] || fail "hierarchy read returned $status"
pass "hierarchy read"

if [[ "$SMOKE_ENABLE_PREDICTION" == "true" ]]; then
  for variable in SMOKE_MODEL_NAME SMOKE_MODEL_VERSION SMOKE_FEATURE_MATRIX_JSON; do
    [[ -n "${!variable:-}" ]] || fail "$variable is required when prediction smoke is enabled"
  done
  prediction_payload="$(python3 - <<'PY'
import json
import os

print(json.dumps({
    "registered_model_name": os.environ["SMOKE_MODEL_NAME"],
    "version_or_alias": os.environ["SMOKE_MODEL_VERSION"],
    "features": json.loads(os.environ["SMOKE_FEATURE_MATRIX_JSON"]),
}))
PY
)" || fail "prediction configuration is invalid"
  status="$(request_status --header "Authorization: Bearer $access_token" \
    --header 'Content-Type: application/json' --data "$prediction_payload" \
    "$API_BASE_URL/ai/predictions/random-forest/regression")"
  [[ "$status" == "200" ]] || fail "prediction returned $status"
  pass "opt-in prediction"
else
  printf 'SKIP  prediction (explicit opt-in required)\n'
fi

logout_payload="$(python3 -c 'import json,sys; print(json.dumps({"refresh_token": sys.argv[1]}))' "$refresh_token")"
status="$(request_status --header 'Content-Type: application/json' \
  --data "$logout_payload" "$API_BASE_URL/auth/logout")"
[[ "$status" == "204" ]] || fail "logout returned $status"
pass "logout"
printf 'Production smoke checks completed successfully.\n'

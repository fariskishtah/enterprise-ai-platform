#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-}"
SUPPORT_TEST_EMAIL="${SUPPORT_TEST_EMAIL:-}"
SUPPORT_TEST_PASSWORD="${SUPPORT_TEST_PASSWORD:-}"

if [[ -z "$API_BASE_URL" || -z "$SUPPORT_TEST_EMAIL" || -z "$SUPPORT_TEST_PASSWORD" ]]; then
  echo "API_BASE_URL, SUPPORT_TEST_EMAIL, and SUPPORT_TEST_PASSWORD are required." >&2
  exit 2
fi
if [[ "$API_BASE_URL" != https://* && "$API_BASE_URL" != http://127.0.0.1:* ]]; then
  echo "Refusing a non-HTTPS remote support test target." >&2
  exit 2
fi

response="$(
  curl --fail-with-body --silent --show-error \
    --header "Content-Type: application/json" \
    --data "$(jq -cn --arg email "$SUPPORT_TEST_EMAIL" --arg password "$SUPPORT_TEST_PASSWORD" '{email:$email,password:$password}')" \
    "$API_BASE_URL/auth/login"
)"
access_token="$(jq -er '.access_token' <<<"$response")"
refresh_token="$(jq -er '.refresh_token' <<<"$response")"
cleanup() {
  if [[ -n "${refresh_token:-}" ]]; then
    curl --silent --show-error --output /dev/null \
      --header "Content-Type: application/json" \
      --data "$(jq -cn --arg token "$refresh_token" '{refresh_token:$token}')" \
      "$API_BASE_URL/auth/logout" || true
  fi
  unset access_token refresh_token response
}
trap cleanup EXIT
idempotency_key="staging-support-test:$(date -u +%Y%m%dT%H%M%SZ)"
result="$(
  curl --fail-with-body --silent --show-error \
    --header "Authorization: Bearer $access_token" \
    --header "Content-Type: application/json" \
    --data "$(jq -cn --arg key "$idempotency_key" '{
      subject:"STAGING TEST — FK SOLUTIONS support delivery",
      category:"technical_problem",
      message:"This is an explicitly requested staging delivery test. No customer data is included.",
      current_page:"/support",
      idempotency_key:$key
    }')" \
    "$API_BASE_URL/support/requests"
)"
jq -r '"Support request \(.id) status: \(.status)"' <<<"$result"
test "$(jq -r '.status' <<<"$result")" = "delivered"

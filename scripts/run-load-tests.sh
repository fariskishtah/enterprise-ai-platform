#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SUITE="${1:-smoke}"
K6_ENV=(-e BASE_URL="$BASE_URL")
for variable in \
  TEST_EMAIL TEST_PASSWORD RAG_TEST_EMAIL RAG_TEST_PASSWORD \
  INVALID_TEST_EMAIL INVALID_TEST_PASSWORD \
  PUBLIC_PROXY \
  SMOKE_VUS SMOKE_DURATION_SECONDS \
  API_VUS API_WARMUP_SECONDS API_STEADY_SECONDS API_COOLDOWN_SECONDS API_PAUSE_SECONDS \
  AUTH_ITERATIONS AUTH_PAUSE_SECONDS \
  RAG_VUS RAG_WARMUP_SECONDS RAG_STEADY_SECONDS RAG_COOLDOWN_SECONDS RAG_PAUSE_SECONDS \
  IMPORT_JOBS IMPORT_IDEMPOTENCY_KEY REPORT_JOBS REPORT_IDEMPOTENCY_KEY \
  STRESS_PEAK_VUS SOAK_VUS SOAK_DURATION_MINUTES \
  ACCEPTANCE_PROFILE \
  ENABLE_TRAINING_LOAD TRAINING_JOBS TRAINING_MAX_POLLS \
  TRAINING_POLL_SECONDS TRAINING_IDEMPOTENCY_KEY; do
  if [[ -n "${!variable:-}" ]]; then
    K6_ENV+=(-e "$variable=${!variable}")
  fi
done

echo "Running k6 performance suite '${SUITE}' against ${BASE_URL}..."

case "$SUITE" in
  smoke)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/smoke.js
    ;;
  api)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/api-load.js
    ;;
  auth)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/auth-load.js
    ;;
  data-rag)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/data-rag-load.js
    ;;
  stress)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/stress.js
    ;;
  soak)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/soak.js
    ;;
  training)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/training-job-load.js
    ;;
  import)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/import-load.js
    ;;
  report)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run /scripts/report-load.js
    ;;
  acceptance)
    profile="${ACCEPTANCE_PROFILE:-smoke}"
    case "$profile" in
      smoke|normal|stress|spike|soak) ;;
      *)
        echo "ACCEPTANCE_PROFILE must be smoke, normal, stress, spike, or soak." >&2
        exit 2
        ;;
    esac
    mkdir -p "$ROOT_DIR/artifacts/load-runs"
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR:/repo:ro" \
      --volume "$ROOT_DIR/artifacts/load-runs:/results" \
      "${K6_ENV[@]}" \
      grafana/k6:2.1.0 \
      run --summary-export="/results/${profile}.json" \
      /repo/tests/load/acceptance.js
    ;;
  inspect)
    for script in smoke.js api-load.js auth-load.js training-job-load.js import-load.js report-load.js data-rag-load.js stress.js soak.js; do
      echo "--- Inspecting ${script} ---"
      docker run --rm \
        --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
        grafana/k6:2.1.0 \
        inspect "/scripts/${script}"
    done
    ;;
  *)
    echo "Unknown suite '${SUITE}'. Available suites: smoke, api, auth, data-rag, stress, soak, training, import, report, acceptance, inspect."
    exit 1
    ;;
esac

echo "k6 suite '${SUITE}' completed successfully."

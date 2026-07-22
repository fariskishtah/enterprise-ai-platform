#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SUITE="${1:-smoke}"

echo "Running k6 performance suite '${SUITE}' against ${BASE_URL}..."

case "$SUITE" in
  smoke)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      -e BASE_URL="$BASE_URL" \
      grafana/k6:2.1.0 \
      run /scripts/smoke.js
    ;;
  api)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      -e BASE_URL="$BASE_URL" \
      grafana/k6:2.1.0 \
      run /scripts/api-load.js
    ;;
  auth)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      -e BASE_URL="$BASE_URL" \
      grafana/k6:2.1.0 \
      run /scripts/auth-load.js
    ;;
  data-rag)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      -e BASE_URL="$BASE_URL" \
      grafana/k6:2.1.0 \
      run /scripts/data-rag-load.js
    ;;
  stress)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      -e BASE_URL="$BASE_URL" \
      grafana/k6:2.1.0 \
      run /scripts/stress.js
    ;;
  soak)
    docker run --rm \
      --network host \
      --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
      -e BASE_URL="$BASE_URL" \
      grafana/k6:2.1.0 \
      run /scripts/soak.js
    ;;
  inspect)
    for script in smoke.js api-load.js auth-load.js training-job-load.js data-rag-load.js stress.js soak.js; do
      echo "--- Inspecting ${script} ---"
      docker run --rm \
        --volume "$ROOT_DIR/performance/k6:/scripts:ro" \
        grafana/k6:2.1.0 \
        inspect "/scripts/${script}"
    done
    ;;
  *)
    echo "Unknown suite '${SUITE}'. Available suites: smoke, api, auth, data-rag, stress, soak, inspect."
    exit 1
    ;;
esac

echo "k6 suite '${SUITE}' completed successfully."

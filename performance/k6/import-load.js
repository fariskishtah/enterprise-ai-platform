import http from "k6/http";
import { check, fail } from "k6";
import exec from "k6/execution";

import {
  BASE_URL,
  bearerParams,
  boundedInteger,
  credentialsConfigured,
  login,
  logout,
  summaryTrendStats,
} from "./common.js";

const importCount = boundedInteger("IMPORT_JOBS", 3, 1, 5);
const idempotencyPrefix =
  __ENV.IMPORT_IDEMPOTENCY_KEY || "k6-bounded-import-v1";
const csv = `timestamp,temperature_c,vibration_mm_s
2026-07-01T08:00:00Z,62.0,1.4
2026-07-01T08:01:00Z,63.0,1.6
2026-07-01T08:02:00Z,64.0,1.8
2026-07-01T08:03:00Z,65.0,2.0
2026-07-01T08:04:00Z,66.0,2.2
2026-07-01T08:05:00Z,67.0,2.4
2026-07-01T08:06:00Z,68.0,2.6
2026-07-01T08:07:00Z,69.0,2.8
2026-07-01T08:08:00Z,70.0,3.0
2026-07-01T08:09:00Z,71.0,3.2
`;

export const options = {
  scenarios: {
    imports: {
      executor: "shared-iterations",
      vus: Math.min(importCount, 3),
      iterations: importCount,
      maxDuration: "2m",
      gracefulStop: "5s",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    "http_req_duration{endpoint:import_upload}": ["p(95)<3000"],
  },
  summaryTrendStats,
};

export function setup() {
  if (!credentialsConfigured()) {
    fail("Import load requires TEST_EMAIL and TEST_PASSWORD.");
  }
  const tokens = login("import_auth_setup");
  if (!tokens.accessToken) fail("Import load requires valid credentials.");
  return tokens;
}

export default function importLoad(data) {
  const iteration = exec.scenario.iterationInTest + 1;
  const key = `${idempotencyPrefix}-${iteration}`;
  const response = http.post(
    `${BASE_URL}/data-onboarding/imports`,
    { file: http.file(csv, `bounded-import-${iteration}.csv`, "text/csv") },
    {
      ...bearerParams(data.accessToken, "import_upload"),
      headers: {
        ...bearerParams(data.accessToken, "import_upload").headers,
        "Idempotency-Key": key,
      },
    },
  );
  const accepted = check(response, {
    "bounded import upload returned 201": (value) => value.status === 201,
    "bounded import exposes ten rows": (value) =>
      value.json("total_rows") === 10,
  });
  if (!accepted) return;

  const replay = http.post(
    `${BASE_URL}/data-onboarding/imports`,
    { file: http.file(csv, `bounded-import-${iteration}.csv`, "text/csv") },
    {
      ...bearerParams(data.accessToken, "import_replay"),
      headers: {
        ...bearerParams(data.accessToken, "import_replay").headers,
        "Idempotency-Key": key,
      },
    },
  );
  check(replay, {
    "import replay is idempotent": (value) =>
      value.status === 201 && value.json("id") === response.json("id"),
  });
}

export function teardown(data) {
  logout(data.refreshSession, "import_auth_logout");
}

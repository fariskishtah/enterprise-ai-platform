import http from "k6/http";
import { check, fail } from "k6";
import exec from "k6/execution";

import {
  BASE_URL,
  bearerParams,
  boundedInteger,
  credentialsConfigured,
  jsonParams,
  login,
  logout,
  summaryTrendStats,
} from "./common.js";

const reportCount = boundedInteger("REPORT_JOBS", 3, 1, 5);
const idempotencyPrefix =
  __ENV.REPORT_IDEMPOTENCY_KEY || "k6-bounded-report-v1";

export const options = {
  scenarios: {
    reports: {
      executor: "shared-iterations",
      vus: Math.min(reportCount, 3),
      iterations: reportCount,
      maxDuration: "2m",
      gracefulStop: "5s",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    "http_req_duration{endpoint:report_create}": ["p(95)<5000"],
    "http_req_duration{endpoint:report_download}": ["p(95)<3000"],
  },
  summaryTrendStats,
};

export function setup() {
  if (!credentialsConfigured()) {
    fail("Report load requires TEST_EMAIL and TEST_PASSWORD.");
  }
  const tokens = login("report_auth_setup");
  if (!tokens.accessToken) fail("Report load requires valid credentials.");
  return tokens;
}

export default function reportLoad(data) {
  const iteration = exec.scenario.iterationInTest + 1;
  const format = iteration % 2 === 0 ? "xlsx" : "pdf";
  const response = http.post(
    `${BASE_URL}/reporting/reports`,
    JSON.stringify({
      report_type: "executive_factory_summary",
      format,
      period_start: "2026-07-01T00:00:00Z",
      period_end: "2026-07-24T00:00:00Z",
      idempotency_key: `${idempotencyPrefix}-${iteration}`,
    }),
    jsonParams("report_create", data.accessToken),
  );
  const created = check(response, {
    "report completed synchronously": (value) =>
      value.status === 201 && value.json("status") === "completed",
    "report has non-trivial size": (value) => value.json("size_bytes") > 500,
  });
  if (!created) return;

  const download = http.get(
    `${BASE_URL}/reporting/reports/${response.json("id")}/download`,
    bearerParams(data.accessToken, "report_download"),
  );
  check(download, {
    "report download returned 200": (value) => value.status === 200,
    "report media type matches format": (value) =>
      format === "pdf"
        ? value.headers["Content-Type"] === "application/pdf"
        : value.headers["Content-Type"] ===
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

export function teardown(data) {
  logout(data.refreshSession, "report_auth_logout");
}

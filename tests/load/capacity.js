import http from "k6/http";
import { check, fail, sleep } from "k6";
import exec from "k6/execution";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "http://127.0.0.1:18080/api").replace(
  /\/+$/,
  "",
);
const WORKLOAD = __ENV.CAPACITY_WORKLOAD || "mixed";
const VUS = boundedStep("CAPACITY_VUS", 10, [10, 25, 50, 100, 250, 500]);
const DURATION_SECONDS = boundedInteger(
  "CAPACITY_DURATION_SECONDS",
  30,
  10,
  120,
);
const PAUSE_SECONDS = boundedNumber("CAPACITY_PAUSE_SECONDS", 2, 0.1, 5);
const WORKLOADS = new Set(["api", "auth", "db", "rag", "mixed"]);
const RAG_LOAD_USER_COUNT = boundedInteger("RAG_LOAD_USER_COUNT", 50, 1, 100);
const RAG_LOAD_EMAIL_PREFIX = __ENV.RAG_LOAD_EMAIL_PREFIX || "phase5-rag";
const RAG_LOAD_EMAIL_DOMAIN = __ENV.RAG_LOAD_EMAIL_DOMAIN || "example.com";
const REFRESH_COOKIE = "factorymind_refresh";
const CSRF_COOKIE = "factorymind_csrf";

if (!WORKLOADS.has(WORKLOAD)) {
  throw new Error("CAPACITY_WORKLOAD must be api, auth, db, rag, or mixed.");
}
if (
  !/^(https?:\/\/)(127\.0\.0\.1|localhost|host\.docker\.internal)(:\d+)?\//.test(
    `${BASE_URL}/`,
  )
) {
  throw new Error("Capacity load tests refuse non-local targets.");
}

const setupErrors = new Rate("capacity_setup_errors");
const steadyErrors = new Rate("capacity_steady_errors");
const setupLatency = new Trend("capacity_setup_latency", true);
const steadyLatency = new Trend("capacity_steady_latency", true);
const apiLatency = new Trend("capacity_api_latency", true);
const authLatency = new Trend("capacity_auth_latency", true);
const dbLatency = new Trend("capacity_db_latency", true);
const ragLatency = new Trend("capacity_rag_latency", true);

export const options = {
  scenarios: {
    capacity:
      WORKLOAD === "auth"
        ? {
            executor: "per-vu-iterations",
            vus: VUS,
            iterations: 1,
            maxDuration: "30s",
          }
        : {
            executor: "constant-vus",
            vus: VUS,
            duration: `${DURATION_SECONDS}s`,
            gracefulStop: "5s",
          },
  },
  thresholds: {
    "checks{phase:steady}": [
      { threshold: "rate>0.98", abortOnFail: true, delayAbortEval: "10s" },
    ],
    capacity_steady_errors: [
      { threshold: "rate<0.02", abortOnFail: true, delayAbortEval: "10s" },
    ],
    "http_req_failed{phase:steady}": [
      { threshold: "rate<0.02", abortOnFail: true, delayAbortEval: "10s" },
    ],
    "http_req_duration{phase:steady}": [
      {
        threshold: WORKLOAD === "auth" ? "p(95)<1500" : "p(95)<1000",
        abortOnFail: true,
        delayAbortEval: "10s",
      },
      { threshold: "p(99)<2500", abortOnFail: true, delayAbortEval: "10s" },
    ],
    "capacity_api_latency{phase:steady}": ["p(95)<750"],
    "capacity_auth_latency{phase:steady}": ["p(95)<1500"],
    "capacity_db_latency{phase:steady}": ["p(95)<1000"],
    "capacity_rag_latency{phase:steady}": ["p(95)<1500"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

function boundedInteger(name, defaultValue, minimum, maximum) {
  const raw = __ENV[name];
  if (raw === undefined || raw === "") return defaultValue;
  if (!/^\d+$/.test(raw)) throw new Error(`${name} must be an integer.`);
  const value = Number(raw);
  if (value < minimum || value > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

function boundedNumber(name, defaultValue, minimum, maximum) {
  const raw = __ENV[name];
  if (raw === undefined || raw === "") return defaultValue;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

function boundedStep(name, defaultValue, allowed) {
  const value = boundedInteger(
    name,
    defaultValue,
    allowed[0],
    allowed[allowed.length - 1],
  );
  if (!allowed.includes(value)) {
    throw new Error(`${name} must be one of ${allowed.join(", ")}.`);
  }
  return value;
}

function requestParams(endpoint, token = null, phase = "steady") {
  const headers = { Accept: "application/json", Host: "127.0.0.1" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return { headers, tags: { endpoint, phase, workload: WORKLOAD } };
}

function jsonParams(endpoint, token = null, phase = "steady") {
  const params = requestParams(endpoint, token, phase);
  params.headers["Content-Type"] = "application/json";
  return params;
}

function cookieValue(response, name) {
  const values = response.cookies[name];
  return Array.isArray(values) && values.length > 0 ? values[0].value : null;
}

function sessionFromResponse(response) {
  const refreshCookie = cookieValue(response, REFRESH_COOKIE);
  const csrfCookie = cookieValue(response, CSRF_COOKIE);
  return refreshCookie && csrfCookie ? { refreshCookie, csrfCookie } : null;
}

function cookieAuthParams(endpoint, session, phase = "steady") {
  return {
    headers: {
      Accept: "application/json",
      Cookie: `${REFRESH_COOKIE}=${session.refreshCookie}; ${CSRF_COOKIE}=${session.csrfCookie}`,
      "X-CSRF-Token": session.csrfCookie,
    },
    tags: { endpoint, phase, workload: WORKLOAD },
  };
}

function record(response, metric, label, expected = 200, phase = "steady") {
  const ok = check(
    response,
    {
      [`${label} returned ${expected}`]: (value) => value.status === expected,
    },
    { phase },
  );
  if (phase === "setup") {
    setupErrors.add(!ok);
    setupLatency.add(response.timings.duration);
  } else {
    steadyErrors.add(!ok);
    steadyLatency.add(response.timings.duration);
  }
  metric.add(response.timings.duration, { phase });
  return ok;
}

function login(email, password, endpoint = "login", phase = "steady") {
  const response = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email, password }),
    jsonParams(endpoint, null, phase),
  );
  if (!record(response, authLatency, endpoint, 200, phase)) return null;
  const refreshSession = sessionFromResponse(response);
  if (!refreshSession) {
    phase === "setup" ? setupErrors.add(true) : steadyErrors.add(true);
    return null;
  }
  return {
    accessToken: response.json("access_token"),
    refreshSession,
  };
}

export function setup() {
  if (!__ENV.TEST_EMAIL || !__ENV.TEST_PASSWORD) {
    fail("TEST_EMAIL and TEST_PASSWORD are required.");
  }
  if (WORKLOAD === "auth") return {};

  const primary = login(
    __ENV.TEST_EMAIL,
    __ENV.TEST_PASSWORD,
    "setup_login",
    "setup",
  );
  if (!primary?.accessToken) fail("Capacity setup login failed.");

  const ragIdentities = [];
  if (WORKLOAD === "rag" || WORKLOAD === "mixed") {
    if (RAG_LOAD_USER_COUNT < VUS) {
      fail("RAG_LOAD_USER_COUNT must be at least CAPACITY_VUS.");
    }
    for (let index = 1; index <= VUS; index += 1) {
      const email = `${RAG_LOAD_EMAIL_PREFIX}-${String(index).padStart(3, "0")}@${RAG_LOAD_EMAIL_DOMAIN}`;
      const identity = login(
        email,
        __ENV.TEST_PASSWORD,
        "rag_pool_setup_login",
        "setup",
      );
      if (!identity?.accessToken) fail("RAG identity pool setup failed.");
      const response = http.get(
        `${BASE_URL}/ai/rag/knowledge-bases?status=ready&limit=20&offset=0`,
        requestParams(
          "knowledge_base_discovery",
          identity.accessToken,
          "setup",
        ),
      );
      if (
        !record(response, dbLatency, "knowledge base discovery", 200, "setup")
      ) {
        fail(
          "RAG capacity setup could not list one identity's knowledge bases.",
        );
      }
      const items = response.json("items");
      if (!Array.isArray(items) || items.length === 0) {
        fail(
          "Each RAG capacity identity requires one ready synthetic knowledge base.",
        );
      }
      ragIdentities.push({
        ...identity,
        knowledgeBaseId: items[0].knowledge_base_id,
      });
    }
  }
  return {
    accessToken: primary.accessToken,
    refreshSession: primary.refreshSession,
    ragIdentities,
  };
}

function apiRead(data, selector) {
  const paths = [
    ["/reporting/executive-dashboard", "dashboard"],
    ["/factories?limit=20&offset=0", "factories"],
    ["/users/me", "identity"],
  ];
  const [path, endpoint] = paths[selector % paths.length];
  const response = http.get(
    `${BASE_URL}${path}`,
    requestParams(endpoint, data.accessToken),
  );
  record(response, apiLatency, endpoint);
}

function dbRead(data, selector) {
  const offset = (selector % 3) * 20;
  const paths = [
    [`/machines?limit=20&offset=${offset}`, "machines_page"],
    [`/operations/alerts?limit=20&offset=${offset}`, "alerts_page"],
    [`/ai/datasets?limit=20&offset=${offset}`, "datasets_page"],
  ];
  const [path, endpoint] = paths[selector % paths.length];
  const response = http.get(
    `${BASE_URL}${path}`,
    requestParams(endpoint, data.accessToken),
  );
  record(response, dbLatency, endpoint);
}

function monitoringRead(data) {
  const response = http.get(
    `${BASE_URL}/operations/alerts?limit=20&offset=0`,
    requestParams("monitoring_alerts", data.accessToken),
  );
  record(response, dbLatency, "monitoring alerts");
}

function ragRead(data) {
  const identity = data.ragIdentities[(__VU - 1) % data.ragIdentities.length];
  const response = http.post(
    `${BASE_URL}/ai/rag/knowledge-bases/${identity.knowledgeBaseId}/search`,
    JSON.stringify({
      query: "What is the local maintenance safety procedure?",
      top_k: 3,
      min_score: 0.05,
    }),
    jsonParams("rag_retrieval", identity.accessToken),
  );
  record(response, ragLatency, "RAG retrieval");
}

function authCycle() {
  const tokens = login(__ENV.TEST_EMAIL, __ENV.TEST_PASSWORD, "auth_login");
  if (!tokens?.accessToken || !tokens.refreshSession) return;
  const identity = http.get(
    `${BASE_URL}/users/me`,
    requestParams("auth_identity", tokens.accessToken),
  );
  record(identity, authLatency, "protected identity");
  const refreshed = http.post(
    `${BASE_URL}/auth/refresh`,
    null,
    cookieAuthParams("auth_refresh", tokens.refreshSession),
  );
  if (!record(refreshed, authLatency, "token refresh")) return;
  const rotatedSession = sessionFromResponse(refreshed);
  if (!rotatedSession) {
    steadyErrors.add(true);
    return;
  }
  const logout = http.post(
    `${BASE_URL}/auth/logout`,
    null,
    cookieAuthParams("auth_logout", rotatedSession),
  );
  record(logout, authLatency, "logout", 204);
}

export default function capacity(data) {
  const selector = exec.scenario.iterationInTest;
  if (WORKLOAD === "api") apiRead(data, selector);
  else if (WORKLOAD === "auth") authCycle();
  else if (WORKLOAD === "db") dbRead(data, selector);
  else if (WORKLOAD === "rag") ragRead(data);
  else {
    const weight = selector % 100;
    if (weight < 40) apiRead(data, selector);
    else if (weight < 70) dbRead(data, selector);
    else if (weight < 85) monitoringRead(data);
    else if (weight < 95) ragRead(data);
    else apiRead(data, 2);
  }
  sleep(PAUSE_SECONDS);
}

export function teardown(data) {
  const sessions = [["capacity_logout", data.refreshSession]];
  for (const identity of data.ragIdentities || []) {
    sessions.push(["capacity_rag_logout", identity.refreshSession]);
  }
  for (const [endpoint, refreshSession] of sessions) {
    if (!refreshSession) continue;
    const response = http.post(
      `${BASE_URL}/auth/logout`,
      null,
      cookieAuthParams(endpoint, refreshSession, "teardown"),
    );
    check(
      response,
      {
        [`${endpoint} returned 204`]: (value) => value.status === 204,
      },
      { phase: "teardown" },
    );
  }
}

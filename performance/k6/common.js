import http from "k6/http";
import { check } from "k6";

const DEFAULT_BASE_URL = "http://host.docker.internal:8000";
const EXPECTED_UNAUTHORIZED = http.expectedStatuses(401);
const REFRESH_COOKIE = "factorymind_refresh";
const CSRF_COOKIE = "factorymind_csrf";

export const summaryTrendStats = [
  "avg",
  "min",
  "med",
  "p(90)",
  "p(95)",
  "p(99)",
  "max",
];

export const BASE_URL = normalizeBaseUrl(__ENV.BASE_URL || DEFAULT_BASE_URL);

export function boundedInteger(name, defaultValue, minimum, maximum) {
  const raw = __ENV[name];
  if (raw === undefined || raw === "") {
    return defaultValue;
  }
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${name} must be an integer.`);
  }
  const value = Number(raw);
  if (value < minimum || value > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

export function boundedNumber(name, defaultValue, minimum, maximum) {
  const raw = __ENV[name];
  if (raw === undefined || raw === "") {
    return defaultValue;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

export function enabled(name) {
  return (__ENV[name] || "").toLowerCase() === "true";
}

export function credentialsConfigured() {
  const hasEmail = Boolean(__ENV.TEST_EMAIL);
  const hasPassword = Boolean(__ENV.TEST_PASSWORD);
  if (hasEmail !== hasPassword) {
    throw new Error("TEST_EMAIL and TEST_PASSWORD must be supplied together.");
  }
  return hasEmail && hasPassword;
}

export function login(endpoint = "auth_success") {
  if (!credentialsConfigured()) {
    return { accessToken: null, refreshSession: null };
  }

  const response = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({
      email: __ENV.TEST_EMAIL,
      password: __ENV.TEST_PASSWORD,
    }),
    jsonParams(endpoint),
  );
  const statusOk = check(response, {
    "login succeeded": (result) => result.status === 200,
  });
  if (!statusOk) {
    return { accessToken: null, refreshSession: null };
  }

  const body = response.json();
  const refreshSession = sessionFromResponse(response);
  const tokenShapeOk = check(
    { body, refreshSession },
    {
      "login returned an access token": (value) =>
        typeof value.body.access_token === "string" &&
        value.body.access_token.length > 0,
      "login returned protected refresh cookies": (value) =>
        Boolean(value.refreshSession),
    },
  );
  if (!tokenShapeOk) {
    return { accessToken: null, refreshSession: null };
  }
  return {
    accessToken: body.access_token,
    refreshSession,
  };
}

export function expectedFailedLogin() {
  const response = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({
      email: __ENV.INVALID_TEST_EMAIL || "missing-k6-user@example.com",
      password: __ENV.INVALID_TEST_PASSWORD || "intentionally-invalid",
    }),
    {
      ...jsonParams("auth_failure"),
      responseCallback: EXPECTED_UNAUTHORIZED,
    },
  );
  check(response, {
    "invalid login was rejected": (result) => result.status === 401,
  });
}

export function logout(refreshSession, endpoint = "auth_logout") {
  if (!refreshSession) {
    return;
  }
  const response = http.post(
    `${BASE_URL}/auth/logout`,
    null,
    cookieAuthParams(endpoint, refreshSession),
  );
  check(response, {
    "refresh token was revoked": (result) => result.status === 204,
  });
}

export function refresh(refreshSession, endpoint = "auth_refresh") {
  if (!refreshSession) {
    return { accessToken: null, refreshSession: null };
  }
  const response = http.post(
    `${BASE_URL}/auth/refresh`,
    null,
    cookieAuthParams(endpoint, refreshSession),
  );
  const statusOk = check(response, {
    "refresh succeeded": (result) => result.status === 200,
  });
  if (!statusOk) {
    return { accessToken: null, refreshSession: null };
  }
  const body = response.json();
  const rotatedSession = sessionFromResponse(response);
  const tokenShapeOk = check(
    { body, rotatedSession },
    {
      "refresh returned an access token": (value) =>
        typeof value.body.access_token === "string" &&
        value.body.access_token.length > 0,
      "refresh rotated protected cookies": (value) =>
        Boolean(value.rotatedSession),
    },
  );
  if (!tokenShapeOk) {
    return { accessToken: null, refreshSession: null };
  }
  return {
    accessToken: body.access_token,
    refreshSession: rotatedSession,
  };
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

function cookieAuthParams(endpoint, session) {
  return {
    headers: {
      Accept: "application/json",
      Cookie: `${REFRESH_COOKIE}=${session.refreshCookie}; ${CSRF_COOKIE}=${session.csrfCookie}`,
      "X-CSRF-Token": session.csrfCookie,
    },
    tags: { endpoint },
  };
}

export function bearerParams(accessToken, endpoint) {
  return {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    tags: { endpoint },
  };
}

export function jsonParams(endpoint, accessToken = null) {
  const headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  return { headers, tags: { endpoint } };
}

function normalizeBaseUrl(rawUrl) {
  const value = rawUrl.replace(/\/+$/, "");
  const match = /^https?:\/\/(\[[^\]]+\]|[^/:]+)(?::\d+)?(?:\/|$)/i.exec(value);
  if (!match) {
    throw new Error("BASE_URL must be an absolute HTTP or HTTPS URL.");
  }

  const hostname = match[1].replace(/^\[|\]$/g, "").toLowerCase();
  const localHost =
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname === "::1" ||
    hostname === "host.docker.internal" ||
    hostname === "backend" ||
    /^127(?:\.\d{1,3}){3}$/.test(hostname);
  if (!localHost && !enabled("ALLOW_REMOTE_TARGET")) {
    throw new Error(
      "Refusing a non-local BASE_URL unless ALLOW_REMOTE_TARGET=true is explicit.",
    );
  }
  return value;
}

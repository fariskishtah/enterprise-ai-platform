import http from 'k6/http';
import { check } from 'k6';

const DEFAULT_BASE_URL = 'http://host.docker.internal:8000';
const EXPECTED_UNAUTHORIZED = http.expectedStatuses(401);

export const summaryTrendStats = [
  'avg',
  'min',
  'med',
  'p(90)',
  'p(95)',
  'p(99)',
  'max',
];

export const BASE_URL = normalizeBaseUrl(__ENV.BASE_URL || DEFAULT_BASE_URL);

export function boundedInteger(name, defaultValue, minimum, maximum) {
  const raw = __ENV[name];
  if (raw === undefined || raw === '') {
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
  if (raw === undefined || raw === '') {
    return defaultValue;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

export function enabled(name) {
  return (__ENV[name] || '').toLowerCase() === 'true';
}

export function credentialsConfigured() {
  const hasEmail = Boolean(__ENV.TEST_EMAIL);
  const hasPassword = Boolean(__ENV.TEST_PASSWORD);
  if (hasEmail !== hasPassword) {
    throw new Error('TEST_EMAIL and TEST_PASSWORD must be supplied together.');
  }
  return hasEmail && hasPassword;
}

export function login(endpoint = 'auth_success') {
  if (!credentialsConfigured()) {
    return { accessToken: null, refreshToken: null };
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
    'login succeeded': (result) => result.status === 200,
  });
  if (!statusOk) {
    return { accessToken: null, refreshToken: null };
  }

  const body = response.json();
  const tokenShapeOk = check(body, {
    'login returned an access token': (value) =>
      typeof value.access_token === 'string' && value.access_token.length > 0,
    'login returned a refresh token': (value) =>
      typeof value.refresh_token === 'string' && value.refresh_token.length > 0,
  });
  if (!tokenShapeOk) {
    return { accessToken: null, refreshToken: null };
  }
  return {
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
  };
}

export function expectedFailedLogin() {
  const response = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({
      email: __ENV.INVALID_TEST_EMAIL || 'missing-k6-user@example.com',
      password: __ENV.INVALID_TEST_PASSWORD || 'intentionally-invalid',
    }),
    {
      ...jsonParams('auth_failure'),
      responseCallback: EXPECTED_UNAUTHORIZED,
    },
  );
  check(response, {
    'invalid login was rejected': (result) => result.status === 401,
  });
}

export function logout(refreshToken, endpoint = 'auth_logout') {
  if (!refreshToken) {
    return;
  }
  const response = http.post(
    `${BASE_URL}/auth/logout`,
    JSON.stringify({ refresh_token: refreshToken }),
    jsonParams(endpoint),
  );
  check(response, {
    'refresh token was revoked': (result) => result.status === 204,
  });
}

export function bearerParams(accessToken, endpoint) {
  return {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    tags: { endpoint },
  };
}

export function jsonParams(endpoint, accessToken = null) {
  const headers = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  return { headers, tags: { endpoint } };
}

function normalizeBaseUrl(rawUrl) {
  const value = rawUrl.replace(/\/+$/, '');
  const match = /^https?:\/\/(\[[^\]]+\]|[^/:]+)(?::\d+)?(?:\/|$)/i.exec(value);
  if (!match) {
    throw new Error('BASE_URL must be an absolute HTTP or HTTPS URL.');
  }

  const hostname = match[1].replace(/^\[|\]$/g, '').toLowerCase();
  const localHost =
    hostname === 'localhost' ||
    hostname.endsWith('.localhost') ||
    hostname === '::1' ||
    hostname === 'host.docker.internal' ||
    hostname === 'backend' ||
    /^127(?:\.\d{1,3}){3}$/.test(hostname);
  if (!localHost && !enabled('ALLOW_REMOTE_TARGET')) {
    throw new Error(
      'Refusing a non-local BASE_URL unless ALLOW_REMOTE_TARGET=true is explicit.',
    );
  }
  return value;
}

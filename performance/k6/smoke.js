import http from 'k6/http';
import { check, sleep } from 'k6';

import {
  BASE_URL,
  bearerParams,
  boundedInteger,
  credentialsConfigured,
  login,
  logout,
  summaryTrendStats,
} from './common.js';

const smokeDurationSeconds = boundedInteger('SMOKE_DURATION_SECONDS', 10, 1, 30);
const smokeVus = boundedInteger('SMOKE_VUS', 1, 1, 2);

export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-vus',
      vus: smokeVus,
      duration: `${smokeDurationSeconds}s`,
      gracefulStop: '2s',
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:health}': ['p(95)<500'],
    'http_req_duration{endpoint:metrics}': ['p(95)<1000'],
    'http_req_duration{endpoint:factories}': ['p(95)<500'],
  },
  summaryTrendStats,
};

export function setup() {
  return credentialsConfigured()
    ? login('smoke_auth_setup')
    : { accessToken: null, refreshToken: null };
}

export default function smoke(data) {
  const healthResponse = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: 'health' },
  });
  check(healthResponse, {
    'health returned 200': (response) => response.status === 200,
    'health returned ok': (response) => response.json('status') === 'ok',
  });

  const metricsResponse = http.get(`${BASE_URL}/metrics`, {
    tags: { endpoint: 'metrics' },
  });
  check(metricsResponse, {
    'metrics returned 200': (response) => response.status === 200,
  });

  if (data.accessToken) {
    const factoriesResponse = http.get(
      `${BASE_URL}/factories?limit=20&offset=0`,
      bearerParams(data.accessToken, 'factories'),
    );
    check(factoriesResponse, {
      'protected factories read returned 200': (response) => response.status === 200,
    });
  }
  sleep(1);
}

export function teardown(data) {
  logout(data.refreshToken, 'smoke_auth_logout');
}

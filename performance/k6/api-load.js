import http from 'k6/http';
import { check, sleep } from 'k6';

import {
  BASE_URL,
  bearerParams,
  boundedInteger,
  boundedNumber,
  credentialsConfigured,
  login,
  logout,
  summaryTrendStats,
} from './common.js';

const targetVus = boundedInteger('API_VUS', 3, 1, 20);
const warmupSeconds = boundedInteger('API_WARMUP_SECONDS', 5, 1, 60);
const steadySeconds = boundedInteger('API_STEADY_SECONDS', 20, 1, 180);
const cooldownSeconds = boundedInteger('API_COOLDOWN_SECONDS', 5, 1, 60);
const pauseSeconds = boundedNumber('API_PAUSE_SECONDS', 0.5, 0.1, 5);

if (warmupSeconds + steadySeconds + cooldownSeconds > 300) {
  throw new Error('The API load profile cannot exceed 300 seconds.');
}

export const options = {
  scenarios: {
    api: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: `${warmupSeconds}s`, target: targetVus },
        { duration: `${steadySeconds}s`, target: targetVus },
        { duration: `${cooldownSeconds}s`, target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    'http_req_duration{endpoint:factories}': ['p(95)<500'],
  },
  summaryTrendStats,
};

export function setup() {
  return credentialsConfigured()
    ? login('api_auth_setup')
    : { accessToken: null, refreshToken: null };
}

export default function apiLoad(data) {
  const healthResponse = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: 'health' },
  });
  check(healthResponse, {
    'health returned 200': (response) => response.status === 200,
  });

  if (data.accessToken) {
    const factoriesResponse = http.get(
      `${BASE_URL}/factories?limit=20&offset=0`,
      bearerParams(data.accessToken, 'factories'),
    );
    check(factoriesResponse, {
      'factories returned 200': (response) => response.status === 200,
      'factories returned a bounded page': (response) =>
        response.json('limit') === 20 && Array.isArray(response.json('items')),
    });
  }
  sleep(pauseSeconds);
}

export function teardown(data) {
  logout(data.refreshToken, 'api_auth_logout');
}

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

const soakVus = boundedInteger('SOAK_VUS', 2, 1, 10);
const soakDurationMinutes = boundedInteger('SOAK_DURATION_MINUTES', 2, 1, 30);

export const options = {
  scenarios: {
    soak: {
      executor: 'constant-vus',
      vus: soakVus,
      duration: `${soakDurationMinutes}m`,
      gracefulStop: '5s',
    },
  },
  thresholds: {
    checks: ['rate>0.98'],
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<1000'],
  },
  summaryTrendStats,
};

export function setup() {
  return credentialsConfigured()
    ? login('soak_auth_setup')
    : { accessToken: null, refreshToken: null };
}

export default function soakLoad(data) {
  const healthRes = http.get(`${BASE_URL}/health`, { tags: { endpoint: 'health' } });
  check(healthRes, { 'health returned 200': (res) => res.status === 200 });

  if (data.accessToken) {
    const datasetsRes = http.get(
      `${BASE_URL}/ai/datasets?limit=20&offset=0`,
      bearerParams(data.accessToken, 'datasets'),
    );
    check(datasetsRes, { 'datasets returned 200': (res) => res.status === 200 });
  }

  sleep(1);
}

export function teardown(data) {
  logout(data.refreshToken, 'soak_auth_logout');
}

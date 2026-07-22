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

const peakVus = boundedInteger('STRESS_PEAK_VUS', 10, 2, 50);

export const options = {
  scenarios: {
    stress: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: Math.floor(peakVus / 2) },
        { duration: '20s', target: peakVus },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    checks: ['rate>0.95'],
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<1500'],
  },
  summaryTrendStats,
};

export function setup() {
  return credentialsConfigured()
    ? login('stress_auth_setup')
    : { accessToken: null, refreshToken: null };
}

export default function stressLoad(data) {
  const healthRes = http.get(`${BASE_URL}/health`, { tags: { endpoint: 'health' } });
  check(healthRes, { 'health returned 200': (res) => res.status === 200 });

  if (data.accessToken) {
    const datasetsRes = http.get(
      `${BASE_URL}/ai/datasets?limit=20&offset=0`,
      bearerParams(data.accessToken, 'datasets'),
    );
    check(datasetsRes, { 'datasets returned 200': (res) => res.status === 200 });
  }

  sleep(0.2);
}

export function teardown(data) {
  logout(data.refreshToken, 'stress_auth_logout');
}

import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';

import {
  BASE_URL,
  bearerParams,
  boundedInteger,
  credentialsConfigured,
  login,
  refresh,
  summaryTrendStats,
} from './common.js';

const soakVus = boundedInteger('SOAK_VUS', 2, 1, 10);
const soakDurationMinutes = boundedInteger('SOAK_DURATION_MINUTES', 2, 1, 30);
const EXPECTED_DATASET_STATUSES = http.expectedStatuses(200, 401);
let vuTokens = null;

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

export default function soakLoad() {
  if (!credentialsConfigured()) {
    exec.test.abort('Soak validation requires TEST_EMAIL and TEST_PASSWORD.');
  }
  const healthRes = http.get(`${BASE_URL}/health`, { tags: { endpoint: 'health' } });
  check(healthRes, { 'health returned 200': (res) => res.status === 200 });

  if (vuTokens === null) {
    vuTokens = login('soak_auth_login');
    if (!vuTokens.accessToken || !vuTokens.refreshToken) {
      exec.test.abort(
        'Soak authentication failed; protected traffic cannot be validated.',
      );
    }
  }
  let datasetsRes = http.get(`${BASE_URL}/ai/datasets?limit=20&offset=0`, {
    ...bearerParams(vuTokens.accessToken, 'datasets'),
    responseCallback: EXPECTED_DATASET_STATUSES,
  });
  if (datasetsRes.status === 401) {
    vuTokens = refresh(vuTokens.refreshToken, 'soak_auth_refresh');
    if (!vuTokens.accessToken || !vuTokens.refreshToken) {
      exec.test.abort(
        'Soak session refresh failed; protected traffic cannot continue.',
      );
    }
    datasetsRes = http.get(
      `${BASE_URL}/ai/datasets?limit=20&offset=0`,
      bearerParams(vuTokens.accessToken, 'datasets_retry'),
    );
  }
  check(datasetsRes, { 'datasets returned 200': (res) => res.status === 200 });

  sleep(1);
}

import { sleep } from 'k6';

import {
  boundedInteger,
  credentialsConfigured,
  expectedFailedLogin,
  login,
  logout,
  summaryTrendStats,
} from './common.js';

const iterations = boundedInteger('AUTH_ITERATIONS', 2, 1, 3);
const pauseSeconds = boundedInteger('AUTH_PAUSE_SECONDS', 10, 5, 30);

export const options = {
  scenarios: {
    authentication: {
      executor: 'shared-iterations',
      vus: 1,
      iterations,
      maxDuration: '2m',
      gracefulStop: '2s',
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:auth_success}': ['p(95)<1500'],
    'http_req_duration{endpoint:auth_failure}': ['p(95)<1500'],
  },
  summaryTrendStats,
};

export default function authLoad() {
  if (credentialsConfigured()) {
    const tokens = login();
    logout(tokens.refreshToken);
  }
  expectedFailedLogin();
  sleep(pauseSeconds);
}

import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import exec from 'k6/execution';

import {
  BASE_URL,
  bearerParams,
  boundedInteger,
  credentialsConfigured,
  enabled,
  jsonParams,
  login,
  logout,
  summaryTrendStats,
} from './common.js';

const jobCount = boundedInteger('TRAINING_JOBS', 1, 1, 3);
const maxPolls = boundedInteger('TRAINING_MAX_POLLS', 6, 1, 20);
const pollSeconds = boundedInteger('TRAINING_POLL_SECONDS', 2, 1, 5);
const idempotencyPrefix =
  __ENV.TRAINING_IDEMPOTENCY_KEY || 'k6-local-small-regression-v1';

if (idempotencyPrefix.length > 120) {
  throw new Error('TRAINING_IDEMPOTENCY_KEY must be 120 characters or fewer.');
}

export const options = {
  scenarios: {
    training: {
      executor: 'shared-iterations',
      vus: 1,
      iterations: jobCount,
      maxDuration: '5m',
      gracefulStop: '5s',
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:training_status}': ['p(95)<500'],
  },
  summaryTrendStats,
};

export function setup() {
  if (!enabled('ENABLE_TRAINING_LOAD')) {
    fail('Training load is disabled; set ENABLE_TRAINING_LOAD=true explicitly.');
  }
  if (!credentialsConfigured()) {
    fail('Training load requires TEST_EMAIL and TEST_PASSWORD.');
  }
  const tokens = login('training_auth_setup');
  if (!tokens.accessToken) {
    fail('Training load requires valid admin or engineer credentials.');
  }
  return tokens;
}

export default function trainingJobLoad(data) {
  const iteration = exec.scenario.iterationInTest + 1;
  const payload = {
    training_features: [[0.0], [1.0], [2.0], [3.0]],
    training_targets: [0.0, 1.0, 2.0, 3.0],
    evaluation_features: [[0.5], [2.5]],
    evaluation_targets: [0.5, 2.5],
    hyperparameters: { n_estimators: 3, n_jobs: 1 },
    random_seed: 11,
    experiment_name: 'k6 local bounded training',
    run_name: 'k6-small-regression',
    tags: { purpose: 'local-performance-verification' },
  };
  const params = jsonParams('training_submit', data.accessToken);
  params.headers['Idempotency-Key'] = `${idempotencyPrefix}-${iteration}`;

  const submission = http.post(
    `${BASE_URL}/ai/training-jobs/random-forest/regression`,
    JSON.stringify(payload),
    params,
  );
  const accepted = check(submission, {
    'training submission was accepted or replayed': (response) =>
      response.status === 200 || response.status === 202,
  });
  if (!accepted) {
    return;
  }

  const statusUrl = submission.json('status_url');
  if (
    !check(statusUrl, {
      'training submission returned a status URL': (value) =>
        typeof value === 'string' && value.startsWith('/ai/training-jobs/'),
    })
  ) {
    return;
  }

  for (let poll = 0; poll < maxPolls; poll += 1) {
    sleep(pollSeconds);
    const statusResponse = http.get(
      `${BASE_URL}${statusUrl}`,
      bearerParams(data.accessToken, 'training_status'),
    );
    const statusOk = check(statusResponse, {
      'training status returned 200': (response) => response.status === 200,
    });
    if (!statusOk) {
      return;
    }
    const jobStatus = statusResponse.json('status');
    check(jobStatus, {
      'training status was recognized': (value) =>
        ['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(value),
    });
    if (['succeeded', 'failed', 'cancelled'].includes(jobStatus)) {
      return;
    }
  }
}

export function teardown(data) {
  logout(data.refreshToken, 'training_auth_logout');
}

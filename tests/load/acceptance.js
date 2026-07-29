import http from 'k6/http';
import { check, fail, sleep } from 'k6';

const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:18080/api').replace(/\/+$/, '');
const PROFILE = __ENV.ACCEPTANCE_PROFILE || 'smoke';
const profiles = {
  smoke: {
    executor: 'constant-vus', vus: 1, duration: '10s', gracefulStop: '3s',
  },
  normal: {
    executor: 'ramping-vus', startVUs: 0,
    stages: [
      { duration: '10s', target: 5 },
      { duration: '30s', target: 5 },
      { duration: '10s', target: 0 },
    ],
    gracefulRampDown: '5s',
  },
  stress: {
    executor: 'ramping-vus', startVUs: 0,
    stages: [
      { duration: '10s', target: 5 },
      { duration: '20s', target: 20 },
      { duration: '10s', target: 0 },
    ],
    gracefulRampDown: '5s',
  },
  spike: {
    executor: 'ramping-vus', startVUs: 1,
    stages: [
      { duration: '3s', target: 20 },
      { duration: '10s', target: 20 },
      { duration: '5s', target: 1 },
    ],
    gracefulRampDown: '3s',
  },
  soak: {
    executor: 'constant-vus', vus: 3, duration: '2m', gracefulStop: '5s',
  },
};

if (!profiles[PROFILE]) {
  throw new Error('Unknown ACCEPTANCE_PROFILE.');
}
if (!/^(https?:\/\/)(127\.0\.0\.1|localhost|host\.docker\.internal)(:\d+)?\//.test(`${BASE_URL}/`)) {
  throw new Error('Acceptance load tests refuse non-local targets.');
}

export const options = {
  scenarios: { acceptance: profiles[PROFILE] },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000', 'p(99)<2000'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function requestParams(endpoint, token = null) {
  const headers = {
    Accept: 'application/json',
    Host: '127.0.0.1',
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return { headers, tags: { endpoint } };
}

function jsonParams(endpoint, token = null) {
  const params = requestParams(endpoint, token);
  params.headers['Content-Type'] = 'application/json';
  return params;
}

function checkedGet(path, endpoint, token, expected = 200) {
  const response = http.get(`${BASE_URL}${path}`, requestParams(endpoint, token));
  check(response, { [`${endpoint} returned ${expected}`]: (value) => value.status === expected });
  return response;
}

function firstItem(response) {
  if (response.status !== 200) return null;
  const items = response.json('items');
  return Array.isArray(items) && items.length > 0 ? items[0] : null;
}

function login(email, password, endpoint) {
  const response = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email, password }),
    jsonParams(endpoint),
  );
  if (!check(response, { [`${endpoint} returned 200`]: (value) => value.status === 200 })) {
    fail(`${endpoint} failed.`);
  }
  return {
    accessToken: response.json('access_token'),
    refreshToken: response.json('refresh_token'),
  };
}

export function setup() {
  if (!__ENV.TEST_EMAIL || !__ENV.TEST_PASSWORD) {
    fail('TEST_EMAIL and TEST_PASSWORD are required.');
  }
  const primary = login(__ENV.TEST_EMAIL, __ENV.TEST_PASSWORD, 'login');
  const ragIdentity = login(
    __ENV.RAG_TEST_EMAIL || __ENV.TEST_EMAIL,
    __ENV.RAG_TEST_PASSWORD || __ENV.TEST_PASSWORD,
    'rag_login',
  );
  const accessToken = primary.accessToken;

  const alerts = checkedGet('/operations/alerts?limit=20&offset=0', 'alerts_discovery', accessToken);
  const alert = firstItem(alerts);
  check(alert, { 'feedback parent alert was discovered': (value) => value !== null });
  if (alert) {
    const feedback = http.post(
      `${BASE_URL}/operations/maintenance-feedback`,
      JSON.stringify({
        alert_id: alert.id,
        outcome: 'no_action_required',
        maintenance_category: 'load_acceptance',
        downtime_minutes: 0,
        summary: `Bounded local k6 acceptance feedback (${PROFILE}).`,
      }),
      jsonParams('feedback_submission', accessToken),
    );
    check(feedback, { 'feedback submission returned 201': (value) => value.status === 201 });
  }

  const datasets = checkedGet('/ai/datasets?limit=20&offset=0', 'datasets_discovery', accessToken);
  const dataset = firstItem(datasets);
  let datasetId = null;
  let versionId = null;
  if (dataset) {
    datasetId = dataset.id;
    const versions = checkedGet(
      `/ai/datasets/${datasetId}/versions?limit=20&offset=0`,
      'versions_discovery',
      accessToken,
    );
    const version = firstItem(versions);
    versionId = version ? version.id : null;
  }

  const knowledgeBases = checkedGet(
    '/ai/rag/knowledge-bases?limit=20&offset=0',
    'knowledge_bases_discovery',
    ragIdentity.accessToken,
  );
  const knowledgeBase = firstItem(knowledgeBases);
  check(knowledgeBase, {
    'RAG knowledge base was discovered': (value) => value !== null,
  });
  if (knowledgeBase) {
    const rag = http.post(
      `${BASE_URL}/ai/rag/knowledge-bases/${knowledgeBase.knowledge_base_id}/search`,
      JSON.stringify({ query: 'local maintenance safety procedure', top_k: 3 }),
      jsonParams('rag_query', ragIdentity.accessToken),
    );
    check(rag, { 'bounded RAG query returned 200': (value) => value.status === 200 });
  }
  return {
    accessToken,
    refreshToken: primary.refreshToken,
    ragRefreshToken: ragIdentity.refreshToken,
    datasetId,
    versionId,
    knowledgeBaseId: knowledgeBase ? knowledgeBase.knowledge_base_id : null,
  };
}

export default function acceptance(data) {
  checkedGet('/health', 'health', null);
  checkedGet('/reporting/executive-dashboard', 'dashboard', data.accessToken);
  checkedGet('/machines?limit=20&offset=0', 'machines', data.accessToken);
  checkedGet('/operations/alerts?limit=20&offset=0', 'alerts', data.accessToken);
  checkedGet('/ai/datasets?limit=20&offset=0', 'datasets', data.accessToken);
  checkedGet('/billing/plans', 'billing_plans', null);
  checkedGet('/billing/subscription', 'subscription_status', data.accessToken);
  checkedGet('/billing/usage', 'usage_status', data.accessToken);
  checkedGet('/billing/history/payments?page=1&page_size=20', 'payment_history', data.accessToken);

  if (data.datasetId && data.versionId) {
    checkedGet(
      `/ai/datasets/${data.datasetId}/versions/${data.versionId}/documents?limit=20&offset=0`,
      'documents',
      data.accessToken,
    );
  }
  sleep(1);
}

export function teardown(data) {
  for (const [endpoint, refreshToken] of [
    ['logout', data.refreshToken],
    ['rag_logout', data.ragRefreshToken],
  ]) {
    if (!refreshToken) continue;
    const response = http.post(
      `${BASE_URL}/auth/logout`,
      JSON.stringify({ refresh_token: refreshToken }),
      jsonParams(endpoint),
    );
    check(response, { [`${endpoint} returned 204`]: (value) => value.status === 204 });
  }
}

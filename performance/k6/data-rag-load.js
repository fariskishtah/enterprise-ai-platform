import http from 'k6/http';
import { check, sleep } from 'k6';

import {
  BASE_URL,
  bearerParams,
  boundedInteger,
  boundedNumber,
  credentialsConfigured,
  jsonParams,
  login,
  logout,
  summaryTrendStats,
} from './common.js';

const targetVus = boundedInteger('RAG_VUS', 2, 1, 10);
const warmupSeconds = boundedInteger('RAG_WARMUP_SECONDS', 5, 1, 60);
const steadySeconds = boundedInteger('RAG_STEADY_SECONDS', 15, 1, 180);
const cooldownSeconds = boundedInteger('RAG_COOLDOWN_SECONDS', 5, 1, 60);
const pauseSeconds = boundedNumber('RAG_PAUSE_SECONDS', 0.5, 0.1, 5);

export const options = {
  scenarios: {
    data_rag: {
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
    'http_req_duration{type:read}': ['p(95)<750'],
    'http_req_duration{type:mutation}': ['p(95)<1500'],
  },
  summaryTrendStats,
};

export function setup() {
  return credentialsConfigured()
    ? login('rag_auth_setup')
    : { accessToken: null, refreshToken: null };
}

export default function dataRagLoad(data) {
  if (!data.accessToken) {
    sleep(pauseSeconds);
    return;
  }

  // 1. Dataset listing & version lookup
  const datasetsRes = http.get(
    `${BASE_URL}/ai/datasets?limit=20&offset=0`,
    { ...bearerParams(data.accessToken, 'datasets_list'), tags: { type: 'read' } },
  );
  check(datasetsRes, {
    'datasets list returned 200': (res) => res.status === 200,
  });

  const datasets = datasetsRes.json('items');
  if (Array.isArray(datasets) && datasets.length > 0) {
    const datasetId = datasets[0].id;
    const versionsRes = http.get(
      `${BASE_URL}/ai/datasets/${datasetId}/versions?limit=20&offset=0`,
      { ...bearerParams(data.accessToken, 'dataset_versions'), tags: { type: 'read' } },
    );
    check(versionsRes, {
      'dataset versions returned 200': (res) => res.status === 200,
    });
  }

  // 2. Training jobs listing
  const jobsRes = http.get(
    `${BASE_URL}/ai/training-jobs?limit=20&offset=0`,
    { ...bearerParams(data.accessToken, 'training_jobs_list'), tags: { type: 'read' } },
  );
  check(jobsRes, {
    'training jobs list returned 200': (res) => res.status === 200,
  });

  // 3. AutoML studies listing
  const automlRes = http.get(
    `${BASE_URL}/ai/automl/studies?limit=20&offset=0`,
    { ...bearerParams(data.accessToken, 'automl_studies_list'), tags: { type: 'read' } },
  );
  check(automlRes, {
    'automl studies list returned 200': (res) => res.status === 200,
  });

  // 4. RAG Knowledge bases listing
  const kbRes = http.get(
    `${BASE_URL}/ai/rag/knowledge-bases?limit=20&offset=0`,
    { ...bearerParams(data.accessToken, 'knowledge_bases_list'), tags: { type: 'read' } },
  );
  check(kbRes, {
    'knowledge bases list returned 200': (res) => res.status === 200,
  });

  const kbs = kbRes.json('items');
  if (Array.isArray(kbs) && kbs.length > 0) {
    const kbId = kbs[0].knowledge_base_id;
    const searchRes = http.post(
      `${BASE_URL}/ai/rag/knowledge-bases/${kbId}/search`,
      JSON.stringify({ query: 'safety procedures', top_k: 3 }),
      { ...jsonParams('knowledge_base_search', data.accessToken), tags: { type: 'read' } },
    );
    check(searchRes, {
      'knowledge base search returned 200': (res) => res.status === 200,
    });
  }

  // 5. Chat conversations listing
  const convsRes = http.get(
    `${BASE_URL}/ai/chat/conversations?limit=20&offset=0`,
    { ...bearerParams(data.accessToken, 'chat_conversations_list'), tags: { type: 'read' } },
  );
  check(convsRes, {
    'chat conversations list returned 200': (res) => res.status === 200,
  });

  sleep(pauseSeconds);
}

export function teardown(data) {
  logout(data.refreshToken, 'rag_auth_logout');
}

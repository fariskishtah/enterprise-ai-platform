import http from "k6/http";
import { check, fail, sleep } from "k6";
import { Trend } from "k6/metrics";

import {
  BASE_URL,
  bearerParams,
  credentialsConfigured,
  enabled,
  jsonParams,
  login,
  logout,
  summaryTrendStats,
} from "./common.js";

const runId = __ENV.DOCUMENT_LOAD_RUN_ID || "phase5-local-v1";
if (!/^[A-Za-z0-9._-]{8,64}$/.test(runId)) {
  throw new Error("DOCUMENT_LOAD_RUN_ID must be 8-64 safe characters.");
}

const processingLatency = new Trend("document_processing_latency", true);
const indexingLatency = new Trend("document_indexing_latency", true);
const syntheticDocument = `FactoryMind Phase 5 synthetic document.
Compressor-Load-01 requires inspection every 14 days.
The safe shutdown order is isolate power, close valve LOAD-17, and verify zero pressure.
Alarm LOAD-417 indicates low oil pressure.
This document contains no customer or production data.`;

export const options = {
  scenarios: {
    document_ingestion: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "2m",
      gracefulStop: "5s",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    "http_req_duration{endpoint:document_upload}": ["p(95)<3000"],
    document_processing_latency: ["p(95)<30000"],
    document_indexing_latency: ["p(95)<30000"],
  },
  summaryTrendStats,
};

export function setup() {
  if (!enabled("ENABLE_DOCUMENT_INGESTION_LOAD")) {
    fail(
      "Document ingestion load is disabled; set ENABLE_DOCUMENT_INGESTION_LOAD=true explicitly.",
    );
  }
  if (!credentialsConfigured()) {
    fail("Document ingestion load requires TEST_EMAIL and TEST_PASSWORD.");
  }
  const tokens = login("document_auth_setup");
  if (!tokens.accessToken)
    fail("Document ingestion load requires valid credentials.");
  return tokens;
}

function waitForVersion(datasetId, versionId, accessToken) {
  const started = Date.now();
  for (let poll = 0; poll < 20; poll += 1) {
    sleep(1);
    const response = http.get(
      `${BASE_URL}/ai/datasets/${datasetId}/versions/${versionId}`,
      bearerParams(accessToken, "document_processing_status"),
    );
    if (
      !check(response, {
        "document status returned 200": (value) => value.status === 200,
      })
    ) {
      return false;
    }
    const status = response.json("status");
    if (status === "ready") {
      processingLatency.add(Date.now() - started);
      return true;
    }
    if (status === "failed") return false;
  }
  return false;
}

function waitForBuild(knowledgeBaseId, buildId, accessToken) {
  const started = Date.now();
  for (let poll = 0; poll < 20; poll += 1) {
    sleep(1);
    const response = http.get(
      `${BASE_URL}/ai/rag/knowledge-bases/${knowledgeBaseId}/builds?limit=20&offset=0`,
      bearerParams(accessToken, "document_index_status"),
    );
    if (
      !check(response, {
        "index status returned 200": (value) => value.status === 200,
      })
    ) {
      return false;
    }
    const builds = response.json("items");
    const build = Array.isArray(builds)
      ? builds.find((item) => item.index_build_id === buildId)
      : null;
    if (build?.status === "succeeded") {
      indexingLatency.add(Date.now() - started);
      return true;
    }
    if (["failed", "cancelled"].includes(build?.status)) return false;
  }
  return false;
}

export default function documentIngest(data) {
  const dataset = http.post(
    `${BASE_URL}/ai/datasets`,
    JSON.stringify({
      name: `Phase 5 document ${runId}`,
      description: "Disposable bounded capacity fixture",
      kind: "document_collection",
    }),
    jsonParams("document_dataset_create", data.accessToken),
  );
  if (
    !check(dataset, {
      "document dataset returned 201": (value) => value.status === 201,
    })
  ) {
    return;
  }
  const datasetId = dataset.json("id");
  const upload = http.post(
    `${BASE_URL}/ai/datasets/${datasetId}/versions`,
    {
      file: http.file(syntheticDocument, `phase5-${runId}.txt`, "text/plain"),
    },
    bearerParams(data.accessToken, "document_upload"),
  );
  if (
    !check(upload, {
      "document upload returned 202": (value) => value.status === 202,
    })
  ) {
    return;
  }
  const versionId = upload.json("id");
  if (
    !check(waitForVersion(datasetId, versionId, data.accessToken), {
      "document processing reached ready": (value) => value === true,
    })
  ) {
    return;
  }

  const knowledgeBase = http.post(
    `${BASE_URL}/ai/rag/knowledge-bases`,
    JSON.stringify({
      name: `Phase 5 knowledge ${runId}`,
      description: "Disposable bounded capacity fixture",
      chunk_size: 300,
      chunk_overlap: 30,
    }),
    jsonParams("document_knowledge_create", data.accessToken),
  );
  if (
    !check(knowledgeBase, {
      "knowledge base returned 201": (value) => value.status === 201,
    })
  ) {
    return;
  }
  const knowledgeBaseId = knowledgeBase.json("knowledge_base_id");
  const attachment = http.post(
    `${BASE_URL}/ai/rag/knowledge-bases/${knowledgeBaseId}/dataset-versions`,
    JSON.stringify({ dataset_version_id: versionId }),
    jsonParams("document_knowledge_attach", data.accessToken),
  );
  if (
    !check(attachment, {
      "document attachment returned 201": (value) => value.status === 201,
    })
  ) {
    return;
  }
  const build = http.post(
    `${BASE_URL}/ai/rag/knowledge-bases/${knowledgeBaseId}/build`,
    null,
    bearerParams(data.accessToken, "document_index_submit"),
  );
  if (
    !check(build, {
      "document index returned 202": (value) => value.status === 202,
    })
  ) {
    return;
  }
  check(
    waitForBuild(
      knowledgeBaseId,
      build.json("index_build_id"),
      data.accessToken,
    ),
    {
      "document index reached succeeded": (value) => value === true,
    },
  );
}

export function teardown(data) {
  logout(data.refreshSession, "document_auth_logout");
}

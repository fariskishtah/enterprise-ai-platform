import { apiRequest } from "./client";

export type KnowledgeBaseStatus =
  "archived" | "draft" | "failed" | "indexing" | "ready";
export type RAGIndexBuildStatus =
  "cancelled" | "failed" | "queued" | "running" | "succeeded";

export interface KnowledgeBaseDatasetVersion {
  readonly dataset_version_id: string;
  readonly attached_at: string;
}

export interface KnowledgeBaseSummary {
  readonly knowledge_base_id: string;
  readonly name: string;
  readonly description: string | null;
  readonly status: KnowledgeBaseStatus;
  readonly embedding_provider: string;
  readonly embedding_model: string;
  readonly embedding_dimension: number;
  readonly attached_dataset_version_count: number;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface KnowledgeBaseDetail extends KnowledgeBaseSummary {
  readonly chunking_configuration: Readonly<Record<string, unknown>>;
  readonly dataset_versions: readonly KnowledgeBaseDatasetVersion[];
  readonly active_index_build_id: string | null;
  readonly indexed_document_count: number;
  readonly indexed_chunk_count: number;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
  readonly archived_at: string | null;
}

export interface RAGIndexBuild {
  readonly index_build_id: string;
  readonly knowledge_base_id: string;
  readonly status: RAGIndexBuildStatus;
  readonly indexed_document_count: number;
  readonly indexed_chunk_count: number;
  readonly embedding_count: number;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly finished_at: string | null;
  readonly cancelled_at: string | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface KnowledgeBasePage {
  readonly items: readonly KnowledgeBaseSummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface RAGIndexBuildPage {
  readonly items: readonly RAGIndexBuild[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface RAGSearchResult {
  readonly chunk_id: string;
  readonly document_id: string;
  readonly dataset_version_id: string;
  readonly rank: number;
  readonly score: number;
  readonly excerpt: string;
  readonly page_number: number | null;
  readonly section: string | null;
  readonly document_title: string;
}

export interface RAGSearchResponse {
  readonly knowledge_base_id: string;
  readonly results: readonly RAGSearchResult[];
  readonly insufficient_evidence: boolean;
}

function queryString(
  values: Readonly<Record<string, number | string | undefined>>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  return `?${query.toString()}`;
}

export function listKnowledgeBases(
  options: {
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
    readonly status?: KnowledgeBaseStatus;
  } = {},
): Promise<KnowledgeBasePage> {
  return apiRequest(
    `/ai/rag/knowledge-bases${queryString({ limit: options.limit ?? 20, offset: options.offset ?? 0, status: options.status })}`,
    { signal: options.signal },
  );
}

export const createKnowledgeBase = (payload: {
  readonly name: string;
  readonly description: string | null;
  readonly chunk_size?: number;
  readonly chunk_overlap?: number;
}): Promise<KnowledgeBaseDetail> =>
  apiRequest("/ai/rag/knowledge-bases", {
    body: JSON.stringify(payload),
    method: "POST",
  });

export const getKnowledgeBase = (id: string, signal?: AbortSignal) =>
  apiRequest<KnowledgeBaseDetail>(`/ai/rag/knowledge-bases/${encodeURIComponent(id)}`, {
    signal,
  });

export const attachDatasetVersion = (
  knowledgeBaseId: string,
  datasetVersionId: string,
): Promise<KnowledgeBaseDatasetVersion> =>
  apiRequest(
    `/ai/rag/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/dataset-versions`,
    {
      body: JSON.stringify({ dataset_version_id: datasetVersionId }),
      method: "POST",
    },
  );

export const detachDatasetVersion = (
  knowledgeBaseId: string,
  datasetVersionId: string,
): Promise<void> =>
  apiRequest(
    `/ai/rag/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/dataset-versions/${encodeURIComponent(datasetVersionId)}`,
    { method: "DELETE" },
  );

export const buildKnowledgeBase = (knowledgeBaseId: string): Promise<RAGIndexBuild> =>
  apiRequest(`/ai/rag/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/build`, {
    method: "POST",
  });

export const cancelKnowledgeBaseBuild = (
  knowledgeBaseId: string,
): Promise<RAGIndexBuild> =>
  apiRequest(
    `/ai/rag/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/cancel-build`,
    { method: "POST" },
  );

export function listKnowledgeBaseBuilds(
  knowledgeBaseId: string,
  options: {
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
  } = {},
): Promise<RAGIndexBuildPage> {
  return apiRequest(
    `/ai/rag/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/builds${queryString({ limit: options.limit ?? 20, offset: options.offset ?? 0 })}`,
    { signal: options.signal },
  );
}

export const searchKnowledgeBase = (
  knowledgeBaseId: string,
  query: string,
  topK: number,
  minScore = 0.05,
): Promise<RAGSearchResponse> =>
  apiRequest(`/ai/rag/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/search`, {
    body: JSON.stringify({ min_score: minScore, query, top_k: topK }),
    method: "POST",
  });

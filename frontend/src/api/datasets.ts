import { apiRequest } from "./client";

export type DatasetKind = "document_collection" | "tabular";
export type DatasetStatus = "active" | "archived" | "failed";
export type DatasetVersionStatus =
  "archived" | "failed" | "pending" | "processing" | "ready";
export type DatasetSourceType =
  "generated" | "imported_from_existing_training_job" | "upload";
export type DocumentProcessingStatus =
  | "cancelled"
  | "chunking"
  | "embedding"
  | "extracting"
  | "failed"
  | "pending"
  | "ready";

export interface DatasetSummary {
  readonly id: string;
  readonly owner_user_id: string;
  readonly name: string;
  readonly description: string | null;
  readonly kind: DatasetKind;
  readonly status: DatasetStatus;
  readonly current_version_id: string | null;
  readonly state_version: number;
  readonly created_at: string;
  readonly updated_at: string;
  readonly archived_at: string | null;
}

export type DatasetDetail = DatasetSummary;

export interface DatasetVersionSummary {
  readonly id: string;
  readonly dataset_id: string;
  readonly version_number: number;
  readonly status: DatasetVersionStatus;
  readonly source_type: DatasetSourceType;
  readonly original_filename: string | null;
  readonly media_type: string;
  readonly size_bytes: number;
  readonly sha256_digest: string;
  readonly row_count: number | null;
  readonly column_count: number | null;
  readonly document_count: number | null;
  readonly chunk_count: number | null;
  readonly created_at: string;
  readonly processing_started_at: string | null;
  readonly ready_at: string | null;
  readonly failed_at: string | null;
  readonly archived_at: string | null;
}

export interface DatasetVersionDetail extends DatasetVersionSummary {
  readonly created_by_user_id: string;
  readonly state_version: number;
  readonly schema_snapshot: Readonly<Record<string, unknown>>;
  readonly lineage_snapshot: Readonly<Record<string, unknown>>;
  readonly ingestion_options: Readonly<Record<string, unknown>>;
  readonly processing_summary: Readonly<Record<string, unknown>>;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface DatasetDocumentSummary {
  readonly id: string;
  readonly dataset_version_id: string;
  readonly document_number: number;
  readonly title: string;
  readonly source_filename: string;
  readonly media_type: string;
  readonly size_bytes: number;
  readonly sha256_digest: string;
  readonly page_count: number | null;
  readonly extracted_character_count: number;
  readonly status: DocumentProcessingStatus;
  readonly created_at: string;
  readonly processing_started_at: string | null;
  readonly ready_at: string | null;
  readonly failed_at: string | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface DatasetDocumentDetail extends DatasetDocumentSummary {
  readonly text_preview: string | null;
}

export interface DatasetPage {
  readonly items: readonly DatasetSummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface DatasetVersionPage {
  readonly items: readonly DatasetVersionSummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface DatasetDocumentPage {
  readonly items: readonly DatasetDocumentSummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface DatasetCreateRequest {
  readonly name: string;
  readonly description: string | null;
  readonly kind: DatasetKind;
}

const DISCOVERY_PAGE_SIZE = 100;
const MAX_DISCOVERED_VERSIONS = 1_000;

export interface DatasetSchemaResponse {
  readonly dataset_id: string;
  readonly version_id: string;
  readonly status: DatasetVersionStatus;
  readonly schema_snapshot: Readonly<Record<string, unknown>>;
}

export interface DatasetArchiveResponse {
  readonly id: string;
  readonly status: DatasetStatus;
  readonly archived_at: string;
}

function queryString(
  values: Readonly<Record<string, number | string | undefined>>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

export function listDatasets(
  options: {
    readonly kind?: DatasetKind;
    readonly status?: DatasetStatus;
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
  } = {},
): Promise<DatasetPage> {
  return apiRequest(
    `/ai/datasets${queryString({ kind: options.kind, status: options.status, limit: options.limit ?? 20, offset: options.offset ?? 0 })}`,
    { signal: options.signal },
  );
}

export const createDatasetRecord = (
  payload: DatasetCreateRequest,
): Promise<DatasetSummary> =>
  apiRequest<DatasetSummary>("/ai/datasets", {
    body: JSON.stringify({
      description: payload.description,
      kind: payload.kind,
      name: payload.name,
    }),
    method: "POST",
  });

export const getDataset = (datasetId: string, signal?: AbortSignal) =>
  apiRequest<DatasetDetail>(`/ai/datasets/${encodeURIComponent(datasetId)}`, {
    signal,
  });

export function listDatasetVersions(
  datasetId: string,
  options: {
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
  } = {},
): Promise<DatasetVersionPage> {
  return apiRequest(
    `/ai/datasets/${encodeURIComponent(datasetId)}/versions${queryString({ limit: options.limit ?? 20, offset: options.offset ?? 0 })}`,
    { signal: options.signal },
  );
}

export async function listAllDatasetVersions(
  datasetId: string,
  options: {
    readonly signal?: AbortSignal;
    readonly maximumItems?: number;
  } = {},
): Promise<readonly DatasetVersionSummary[]> {
  const maximumItems = options.maximumItems ?? MAX_DISCOVERED_VERSIONS;
  const items: DatasetVersionSummary[] = [];
  let offset = 0;
  let total = 0;
  do {
    const page = await listDatasetVersions(datasetId, {
      limit: DISCOVERY_PAGE_SIZE,
      offset,
      signal: options.signal,
    });
    total = page.total;
    if (total > maximumItems) {
      throw new Error(
        `This dataset has ${total.toLocaleString()} versions. Discovery is limited to ${maximumItems.toLocaleString()} versions at a time.`,
      );
    }
    items.push(...page.items);
    offset += page.items.length;
    if (page.items.length === 0 && offset < total) {
      throw new Error("Dataset version pagination did not advance.");
    }
  } while (offset < total);
  return items;
}

export function createDatasetVersion(
  datasetId: string,
  file: File,
  options: { readonly splitColumn?: string; readonly targetColumn?: string } = {},
): Promise<DatasetVersionDetail> {
  const body = new FormData();
  body.append("file", file, file.name);
  if (options.targetColumn) body.append("target_column", options.targetColumn);
  if (options.splitColumn) body.append("split_column", options.splitColumn);
  return apiRequest(`/ai/datasets/${encodeURIComponent(datasetId)}/versions`, {
    body,
    method: "POST",
  });
}

export const getDatasetVersion = (
  datasetId: string,
  versionId: string,
  signal?: AbortSignal,
) =>
  apiRequest<DatasetVersionDetail>(
    `/ai/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}`,
    { signal },
  );

export const getDatasetVersionSchema = (
  datasetId: string,
  versionId: string,
  signal?: AbortSignal,
) =>
  apiRequest<DatasetSchemaResponse>(
    `/ai/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/schema`,
    { signal },
  );

export function listDatasetDocuments(
  datasetId: string,
  versionId: string,
  options: {
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
  } = {},
): Promise<DatasetDocumentPage> {
  return apiRequest(
    `/ai/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/documents${queryString({ limit: options.limit ?? 20, offset: options.offset ?? 0 })}`,
    { signal: options.signal },
  );
}

export const getDatasetDocument = (
  datasetId: string,
  versionId: string,
  documentId: string,
  signal?: AbortSignal,
) =>
  apiRequest<DatasetDocumentDetail>(
    `/ai/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/documents/${encodeURIComponent(documentId)}`,
    { signal },
  );

export const archiveDataset = (datasetId: string): Promise<DatasetArchiveResponse> =>
  apiRequest(`/ai/datasets/${encodeURIComponent(datasetId)}/archive`, {
    method: "POST",
  });

import { apiRequest } from "./client";
import type { PaginatedResponse } from "./hierarchy";

export type ReadingQuality = "BAD" | "GOOD" | "MISSING" | "OUTLIER";
export type ReadingSource = "API" | "CSV" | "SIMULATION";
export type UploadJobStatus = "COMPLETED" | "FAILED" | "PENDING" | "PROCESSING";

export interface SensorReading {
  readonly batch_id: string | null;
  readonly created_at: string;
  readonly id: string;
  readonly quality: ReadingQuality;
  readonly sensor_id: string;
  readonly source: ReadingSource;
  readonly timestamp: string;
  readonly value: number;
}

export interface SensorReadingInput {
  readonly quality: ReadingQuality;
  readonly sensor_id: string;
  readonly source: ReadingSource;
  readonly timestamp: string;
  readonly value: number;
}

export interface UploadJob {
  readonly created_at: string;
  readonly created_by: string;
  readonly filename: string;
  readonly finished_at: string | null;
  readonly id: string;
  readonly invalid_rows: number;
  readonly source: ReadingSource;
  readonly started_at: string | null;
  readonly status: UploadJobStatus;
  readonly total_rows: number;
  readonly valid_rows: number;
}

export interface ReadingListOptions {
  readonly limit?: number;
  readonly offset?: number;
  readonly quality?: ReadingQuality;
  readonly signal?: AbortSignal;
  readonly sortOrder?: "asc" | "desc";
  readonly source?: ReadingSource;
  readonly timestampFrom?: string;
  readonly timestampTo?: string;
}

export interface UploadJobListOptions {
  readonly limit?: number;
  readonly offset?: number;
  readonly signal?: AbortSignal;
  readonly status?: UploadJobStatus;
}

function queryString(values: Record<string, number | string | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const encoded = query.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

export function listSensorReadings(
  sensorId: string,
  options: ReadingListOptions = {},
): Promise<PaginatedResponse<SensorReading>> {
  return apiRequest(
    `/sensors/${sensorId}/readings${queryString({
      limit: options.limit ?? 20,
      offset: options.offset ?? 0,
      quality: options.quality,
      source: options.source,
      timestamp_from: options.timestampFrom,
      timestamp_to: options.timestampTo,
      sort_by: "timestamp",
      sort_order: options.sortOrder ?? "desc",
    })}`,
    { signal: options.signal },
  );
}

export function createSensorReading(
  payload: SensorReadingInput,
): Promise<SensorReading> {
  return apiRequest("/sensor-readings", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function listUploadJobs(
  options: UploadJobListOptions = {},
): Promise<PaginatedResponse<UploadJob>> {
  return apiRequest(
    `/upload-jobs${queryString({
      limit: options.limit ?? 20,
      offset: options.offset ?? 0,
      sort_by: "created_at",
      sort_order: "desc",
      status: options.status,
    })}`,
    { signal: options.signal },
  );
}

export function getUploadJob(
  uploadJobId: string,
  signal?: AbortSignal,
): Promise<UploadJob> {
  return apiRequest(`/upload-jobs/${uploadJobId}`, { signal });
}

export function createUploadJob(filename: string): Promise<UploadJob> {
  return apiRequest("/upload-jobs", {
    body: JSON.stringify({ filename, source: "CSV" }),
    method: "POST",
  });
}

export function uploadCsvFile(uploadJobId: string, file: File): Promise<UploadJob> {
  const body = new FormData();
  body.append("file", file, file.name);
  return apiRequest(`/upload-jobs/${uploadJobId}/csv`, { body, method: "POST" });
}

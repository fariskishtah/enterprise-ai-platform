import { ApiError } from "../../api/client";

export function hierarchyError(error: unknown): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : "An unexpected error occurred.";
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function displayValue(value: string | null): string {
  return value ?? "Not provided";
}

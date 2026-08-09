import {
  clearStoredTokens,
  readStoredTokens,
  readTokenRevision,
  storeTokenPair,
  type TokenPair,
} from "./tokenStore";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : "/api")
).replace(/\/$/, "");
const ACCESS_EXPIRY_MARGIN_MS = 5_000;
const CSRF_COOKIE_NAME = "factorymind_csrf";

interface RequestOptions {
  readonly authenticated?: boolean;
  readonly retryAfterRefresh?: boolean;
}

type SessionExpiredHandler = () => void;

let refreshRequest: Promise<string> | null = null;
let sessionExpiredHandler: SessionExpiredHandler | null = null;

export class ApiError extends Error {
  readonly code: string | null;
  readonly paymentId: string | null;
  readonly status: number;

  constructor(
    message: string,
    status: number,
    context: { readonly code?: string; readonly paymentId?: string } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = context.code ?? null;
    this.paymentId = context.paymentId ?? null;
    this.status = status;
  }
}

export function isRequestCancelled(
  error: unknown,
  signal?: AbortSignal | null,
): boolean {
  if (signal?.aborted === true) return true;
  if (error instanceof DOMException && error.name === "AbortError") return true;
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

function errorMessage(payload: unknown, fallback: string): string {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  if (
    typeof payload === "object" &&
    payload !== null &&
    "detail" in payload &&
    typeof payload.detail === "object" &&
    payload.detail !== null &&
    "message" in payload.detail &&
    typeof payload.detail.message === "string"
  ) {
    return payload.detail.message;
  }
  if (
    typeof payload === "object" &&
    payload !== null &&
    "detail" in payload &&
    Array.isArray(payload.detail)
  ) {
    const issue = payload.detail.find(
      (item): item is { readonly loc?: readonly unknown[]; readonly msg: string } =>
        typeof item === "object" &&
        item !== null &&
        "msg" in item &&
        typeof item.msg === "string",
    );
    if (issue !== undefined) {
      const field = issue.loc?.at(-1);
      return typeof field === "string"
        ? `${field.replaceAll("_", " ")}: ${issue.msg}`
        : issue.msg;
    }
  }
  return fallback;
}

function errorContext(payload: unknown): {
  readonly code?: string;
  readonly paymentId?: string;
} {
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("detail" in payload) ||
    typeof payload.detail !== "object" ||
    payload.detail === null
  )
    return {};
  const detail = payload.detail;
  return {
    ...("code" in detail && typeof detail.code === "string"
      ? { code: detail.code }
      : {}),
    ...("payment_id" in detail && typeof detail.payment_id === "string"
      ? { paymentId: detail.payment_id }
      : {}),
  };
}

function isTokenPair(payload: unknown): payload is TokenPair {
  return (
    typeof payload === "object" &&
    payload !== null &&
    "access_token" in payload &&
    typeof payload.access_token === "string" &&
    "expires_in" in payload &&
    typeof payload.expires_in === "number" &&
    Number.isFinite(payload.expires_in) &&
    payload.expires_in > 0 &&
    "token_type" in payload &&
    payload.token_type === "bearer"
  );
}

function readCsrfToken(): string | null {
  const prefix = `${CSRF_COOKIE_NAME}=`;
  const cookie = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix));
  return cookie === undefined ? null : decodeURIComponent(cookie.slice(prefix.length));
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return undefined;
  }
  const contentType = response.headers.get("content-type") ?? "";
  try {
    return contentType.includes("application/json")
      ? await response.json()
      : await response.text();
  } catch {
    throw new ApiError("The server returned an invalid response.", response.status);
  }
}

export async function refreshAccessToken(): Promise<string> {
  if (refreshRequest !== null) {
    return refreshRequest;
  }

  const revision = readTokenRevision();

  refreshRequest = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        credentials: "include",
        headers: { "X-CSRF-Token": readCsrfToken() ?? "" },
        method: "POST",
      });
      const payload = await parseBody(response);
      if (!response.ok) {
        throw new ApiError(
          errorMessage(payload, "Your session could not be refreshed."),
          response.status,
        );
      }
      if (!isTokenPair(payload)) {
        throw new ApiError("The server returned an invalid session response.", 0);
      }
      if (readTokenRevision() !== revision) {
        throw new ApiError("The session changed while it was being refreshed.", 401);
      }
      return storeTokenPair(payload).accessToken;
    } catch (error) {
      clearStoredTokens();
      sessionExpiredHandler?.();
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError("Unable to refresh your session.", 0);
    } finally {
      refreshRequest = null;
    }
  })();

  return refreshRequest;
}

export function setSessionExpiredHandler(handler: SessionExpiredHandler | null): void {
  sessionExpiredHandler = handler;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const authenticated = options.authenticated ?? true;
  let accessToken: string | null = null;

  if (authenticated) {
    const tokens = readStoredTokens();
    accessToken =
      tokens === null ||
      tokens.accessTokenExpiresAt <= Date.now() + ACCESS_EXPIRY_MARGIN_MS
        ? await refreshAccessToken()
        : tokens.accessToken;
  }

  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken !== null) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const csrfToken = readCsrfToken();
  if (csrfToken !== null && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
  } catch (error) {
    if (isRequestCancelled(error, init.signal)) throw error;
    throw new ApiError("Unable to reach the server. Please try again.", 0);
  }

  const method = (init.method ?? "GET").toUpperCase();
  const safeToReplay = method === "GET" || method === "HEAD" || method === "OPTIONS";
  if (
    response.status === 401 &&
    authenticated &&
    safeToReplay &&
    (options.retryAfterRefresh ?? true)
  ) {
    const refreshedAccessToken = await refreshAccessToken();
    headers.set("Authorization", `Bearer ${refreshedAccessToken}`);
    return apiRequest<T>(
      path,
      { ...init, headers },
      {
        authenticated: true,
        retryAfterRefresh: false,
      },
    );
  }

  const payload = await parseBody(response);
  if (response.status === 401 && authenticated) {
    clearStoredTokens();
    sessionExpiredHandler?.();
  }
  if (!response.ok) {
    throw new ApiError(
      errorMessage(payload, `Request failed with status ${response.status}.`),
      response.status,
      errorContext(payload),
    );
  }
  return payload as T;
}

export async function apiDownload(path: string): Promise<Blob> {
  const tokens = readStoredTokens();
  const accessToken =
    tokens === null ||
    tokens.accessTokenExpiresAt <= Date.now() + ACCESS_EXPIRY_MARGIN_MS
      ? await refreshAccessToken()
      : tokens.accessToken;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: "include",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    throw new ApiError("Unable to reach the server. Please try again.", 0);
  }
  if (!response.ok) {
    const payload = await parseBody(response);
    throw new ApiError(
      errorMessage(payload, `Request failed with status ${response.status}.`),
      response.status,
    );
  }
  return response.blob();
}

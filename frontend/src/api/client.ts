import {
  clearStoredTokens,
  readStoredTokens,
  storeTokenPair,
  type TokenPair,
} from "./sessionStorage";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "http://localhost:8000" : "/api")
).replace(/\/$/, "");
const ACCESS_EXPIRY_MARGIN_MS = 5_000;

interface RequestOptions {
  readonly authenticated?: boolean;
  readonly retryAfterRefresh?: boolean;
}

type SessionExpiredHandler = () => void;

let refreshRequest: Promise<string> | null = null;
let sessionExpiredHandler: SessionExpiredHandler | null = null;

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
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
  return fallback;
}

function isTokenPair(payload: unknown): payload is TokenPair {
  return (
    typeof payload === "object" &&
    payload !== null &&
    "access_token" in payload &&
    typeof payload.access_token === "string" &&
    "refresh_token" in payload &&
    typeof payload.refresh_token === "string" &&
    "expires_in" in payload &&
    typeof payload.expires_in === "number" &&
    Number.isFinite(payload.expires_in) &&
    payload.expires_in > 0 &&
    "token_type" in payload &&
    payload.token_type === "bearer"
  );
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

async function refreshAccessToken(): Promise<string> {
  if (refreshRequest !== null) {
    return refreshRequest;
  }

  const tokens = readStoredTokens();
  if (tokens === null) {
    sessionExpiredHandler?.();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  refreshRequest = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        body: JSON.stringify({ refresh_token: tokens.refreshToken }),
        headers: { "Content-Type": "application/json" },
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
      if (readStoredTokens()?.refreshToken !== tokens.refreshToken) {
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
    if (tokens === null) {
      sessionExpiredHandler?.();
      throw new ApiError("Authentication is required.", 401);
    }
    accessToken =
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

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
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
    );
  }
  return payload as T;
}

export async function apiDownload(path: string): Promise<Blob> {
  const tokens = readStoredTokens();
  if (tokens === null) {
    sessionExpiredHandler?.();
    throw new ApiError("Authentication is required.", 401);
  }
  const accessToken =
    tokens.accessTokenExpiresAt <= Date.now() + ACCESS_EXPIRY_MARGIN_MS
      ? await refreshAccessToken()
      : tokens.accessToken;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
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

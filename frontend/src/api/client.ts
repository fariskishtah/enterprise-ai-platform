import {
  clearStoredTokens,
  readStoredTokens,
  storeTokenPair,
  type TokenPair,
} from "./sessionStorage";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
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

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return undefined;
  }
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("application/json") ? response.json() : response.text();
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
      return storeTokenPair(payload as TokenPair).accessToken;
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
  } catch {
    throw new ApiError("Unable to reach the server. Please try again.", 0);
  }

  if (response.status === 401 && authenticated && (options.retryAfterRefresh ?? true)) {
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

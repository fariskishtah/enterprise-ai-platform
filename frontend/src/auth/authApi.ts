import { apiRequest } from "../api/client";
import type { TokenPair } from "../api/sessionStorage";

export type UserRole = "admin" | "engineer" | "operator";

export interface CurrentUser {
  readonly company_id: string;
  readonly created_at: string;
  readonly email: string;
  readonly id: string;
  readonly is_active: boolean;
  readonly role: UserRole;
  readonly updated_at: string;
}

export interface LoginRequest {
  readonly email: string;
  readonly password: string;
}

export function login(payload: LoginRequest): Promise<TokenPair> {
  return apiRequest<TokenPair>(
    "/auth/login",
    { body: JSON.stringify(payload), method: "POST" },
    { authenticated: false },
  );
}

export function getCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/users/me");
}

export function revokeSession(refreshToken: string): Promise<void> {
  return apiRequest<void>(
    "/auth/logout",
    {
      body: JSON.stringify({ refresh_token: refreshToken }),
      method: "POST",
    },
    { authenticated: false },
  );
}

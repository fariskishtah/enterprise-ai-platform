import { apiRequest } from "../api/client";
import type { TokenPair } from "../api/sessionStorage";

export type UserRole = "admin" | "engineer" | "operator";

export interface CurrentUser {
  readonly company_id: string;
  readonly created_at: string;
  readonly email: string;
  readonly id: string;
  readonly is_active: boolean;
  readonly full_name: string | null;
  readonly role: UserRole;
  readonly updated_at: string;
}

export interface LoginRequest {
  readonly email: string;
  readonly password: string;
}

export interface RegisterRequest {
  readonly company_name: string;
  readonly email: string;
  readonly name: string;
  readonly password: string;
}

export interface PasswordResetRequestResponse {
  readonly local_reset_token: string | null;
  readonly message: string;
}

export function registerAccount(payload: RegisterRequest): Promise<CurrentUser> {
  return apiRequest<CurrentUser>(
    "/auth/register",
    { body: JSON.stringify(payload), method: "POST" },
    { authenticated: false },
  );
}

export function login(payload: LoginRequest): Promise<TokenPair> {
  return apiRequest<TokenPair>(
    "/auth/login",
    { body: JSON.stringify(payload), method: "POST" },
    { authenticated: false },
  );
}

export function requestPasswordReset(
  email: string,
): Promise<PasswordResetRequestResponse> {
  return apiRequest<PasswordResetRequestResponse>(
    "/auth/password-reset/request",
    { body: JSON.stringify({ email }), method: "POST" },
    { authenticated: false },
  );
}

export function completePasswordReset(
  token: string,
  newPassword: string,
): Promise<void> {
  return apiRequest<void>(
    "/auth/password-reset/complete",
    { body: JSON.stringify({ new_password: newPassword, token }), method: "POST" },
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

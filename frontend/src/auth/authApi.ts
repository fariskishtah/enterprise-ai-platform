import { apiRequest } from "../api/client";
import type { TokenPair } from "../api/sessionStorage";

export type UserRole =
  "owner" | "admin" | "engineer" | "operator" | "analyst" | "viewer";

export interface CurrentUser {
  readonly company_id: string;
  readonly created_at: string;
  readonly email: string;
  readonly id: string;
  readonly is_active: boolean;
  readonly is_email_verified?: boolean;
  readonly email_verified_at?: string | null;
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

export interface RegistrationResponse extends CurrentUser {
  readonly local_verification_token: string | null;
}

export interface EmailVerificationStatus {
  readonly email: string;
  readonly is_verified: boolean;
  readonly verified_at: string | null;
  readonly resend_available_in_seconds: number;
}

export interface EmailVerificationResult {
  readonly message: string;
  readonly status: "already_verified" | "verified";
}

export interface EmailVerificationResendResult {
  readonly local_verification_token: string | null;
  readonly message: string;
  readonly resend_available_in_seconds: number;
}

export function registerAccount(
  payload: RegisterRequest,
): Promise<RegistrationResponse> {
  return apiRequest<RegistrationResponse>(
    "/auth/register",
    { body: JSON.stringify(payload), method: "POST" },
    { authenticated: false },
  );
}

export function getEmailVerificationStatus(): Promise<EmailVerificationStatus> {
  return apiRequest<EmailVerificationStatus>("/auth/email-verification/status");
}

export function resendEmailVerification(): Promise<EmailVerificationResendResult> {
  return apiRequest<EmailVerificationResendResult>("/auth/email-verification/resend", {
    method: "POST",
  });
}

export function verifyEmail(token: string): Promise<EmailVerificationResult> {
  return apiRequest<EmailVerificationResult>(
    "/auth/email-verification/verify",
    { body: JSON.stringify({ token }), method: "POST" },
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

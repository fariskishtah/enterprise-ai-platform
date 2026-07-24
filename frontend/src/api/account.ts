import { apiRequest } from "./client";

export type UserRole = "admin" | "engineer" | "operator";

export interface CompanyUser {
  readonly company_id: string;
  readonly created_at: string;
  readonly email: string;
  readonly id: string;
  readonly is_active: boolean;
  readonly role: UserRole;
  readonly updated_at: string;
}

export interface UserPage {
  readonly items: readonly CompanyUser[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export interface ActiveSession {
  readonly created_at: string;
  readonly expires_at: string;
  readonly id: string;
  readonly last_seen_at: string | null;
  readonly source_ip: string | null;
  readonly user_agent_summary: string | null;
}

export function listUsers(query: {
  readonly isActive?: boolean;
  readonly offset?: number;
  readonly role?: UserRole;
  readonly signal?: AbortSignal;
}): Promise<UserPage> {
  const params = new URLSearchParams({
    limit: "50",
    offset: String(query.offset ?? 0),
  });
  if (query.role) params.set("role", query.role);
  if (query.isActive !== undefined) params.set("is_active", String(query.isActive));
  return apiRequest<UserPage>(`/users?${params}`, { signal: query.signal });
}

export function createUser(payload: {
  readonly email: string;
  readonly password: string;
  readonly role: UserRole;
}): Promise<CompanyUser> {
  return apiRequest<CompanyUser>("/users", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function updateUser(
  userId: string,
  payload: { readonly is_active?: boolean; readonly role?: UserRole },
): Promise<CompanyUser> {
  return apiRequest<CompanyUser>(`/users/${userId}`, {
    body: JSON.stringify(payload),
    method: "PATCH",
  });
}

export function changePassword(payload: {
  readonly current_password: string;
  readonly new_password: string;
}): Promise<void> {
  return apiRequest<void>("/users/me/password", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function listSessions(signal?: AbortSignal): Promise<{
  readonly items: readonly ActiveSession[];
}> {
  return apiRequest("/users/me/sessions", { signal });
}

export function revokeActiveSession(sessionId: string): Promise<void> {
  return apiRequest<void>(`/users/me/sessions/${sessionId}`, { method: "DELETE" });
}

export function revokeOtherSessions(refreshToken: string): Promise<void> {
  return apiRequest<void>("/users/me/sessions/revoke-others", {
    body: JSON.stringify({ refresh_token: refreshToken }),
    method: "POST",
  });
}

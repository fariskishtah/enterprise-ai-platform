import { apiRequest } from "./client";

export type UserRole =
  "owner" | "admin" | "engineer" | "operator" | "analyst" | "viewer";

export interface CompanyUser {
  readonly company_id: string;
  readonly created_at: string;
  readonly email: string;
  readonly id: string;
  readonly is_active: boolean;
  readonly full_name: string | null;
  readonly role: UserRole;
  readonly updated_at: string;
}

export interface UserPage {
  readonly items: readonly CompanyUser[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export interface TeamInvitation {
  readonly accepted_at: string | null;
  readonly company_id: string;
  readonly created_at: string;
  readonly expires_at: string;
  readonly id: string;
  readonly invited_email: string;
  readonly inviter_user_id: string;
  readonly last_sent_at: string;
  readonly local_invitation_token: string | null;
  readonly revoked_at: string | null;
  readonly role: UserRole;
  readonly send_count: number;
}

export interface InvitationPage {
  readonly items: readonly TeamInvitation[];
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
  readonly full_name?: string;
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

export function listInvitations(signal?: AbortSignal): Promise<InvitationPage> {
  return apiRequest<InvitationPage>("/team/invitations?limit=50&offset=0", {
    signal,
  });
}

export function createInvitation(payload: {
  readonly email: string;
  readonly role: UserRole;
}): Promise<TeamInvitation> {
  return apiRequest<TeamInvitation>("/team/invitations", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function resendInvitation(invitationId: string): Promise<TeamInvitation> {
  return apiRequest<TeamInvitation>(`/team/invitations/${invitationId}/resend`, {
    method: "POST",
  });
}

export function revokeInvitation(invitationId: string): Promise<void> {
  return apiRequest<void>(`/team/invitations/${invitationId}`, {
    method: "DELETE",
  });
}

export function acceptInvitation(payload: {
  readonly full_name?: string;
  readonly password?: string;
  readonly token: string;
}): Promise<{ readonly status: "accepted"; readonly user: CompanyUser }> {
  return apiRequest(
    "/team/invitations/accept",
    { body: JSON.stringify(payload), method: "POST" },
    { authenticated: false },
  );
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

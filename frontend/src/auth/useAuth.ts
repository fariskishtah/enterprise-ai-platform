import { createContext, useContext } from "react";

import type { CurrentUser, LoginRequest, UserRole } from "./authApi";

export type AuthStatus = "authenticated" | "loading" | "unauthenticated";

export interface AuthContextValue {
  readonly clearNotice: () => void;
  readonly isAuthenticated: boolean;
  readonly login: (credentials: LoginRequest) => Promise<void>;
  readonly logout: () => Promise<void>;
  readonly notice: string | null;
  readonly role: UserRole | null;
  readonly status: AuthStatus;
  readonly user: CurrentUser | null;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used within AuthProvider.");
  }
  return context;
}

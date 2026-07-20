import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import { setSessionExpiredHandler } from "../api/client";
import {
  clearStoredTokens,
  readStoredTokens,
  storeTokenPair,
} from "../api/sessionStorage";
import {
  getCurrentUser,
  login as requestLogin,
  revokeSession,
  type CurrentUser,
  type LoginRequest,
} from "./authApi";
import { AuthContext, type AuthContextValue, type AuthStatus } from "./useAuth";

export function AuthProvider({
  children,
}: {
  readonly children: ReactNode;
}): ReactElement {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const expireSession = useCallback((): void => {
    clearStoredTokens();
    setUser(null);
    setNotice("Your session expired. Please sign in again.");
    setStatus("unauthenticated");
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(expireSession);
    return () => setSessionExpiredHandler(null);
  }, [expireSession]);

  useEffect(() => {
    let active = true;

    const initialize = async (): Promise<void> => {
      if (readStoredTokens() === null) {
        if (active) {
          setStatus("unauthenticated");
        }
        return;
      }
      try {
        const currentUser = await getCurrentUser();
        if (active) {
          setUser(currentUser);
          setStatus("authenticated");
        }
      } catch {
        clearStoredTokens();
        if (active) {
          setUser(null);
          setNotice("Your session expired. Please sign in again.");
          setStatus("unauthenticated");
        }
      }
    };

    void initialize();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (credentials: LoginRequest): Promise<void> => {
    const tokens = await requestLogin(credentials);
    storeTokenPair(tokens);
    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setNotice(null);
      setStatus("authenticated");
    } catch (error) {
      clearStoredTokens();
      throw error;
    }
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    const refreshToken = readStoredTokens()?.refreshToken;
    clearStoredTokens();
    setUser(null);
    setNotice("You have been signed out.");
    setStatus("unauthenticated");
    if (refreshToken !== undefined) {
      try {
        await revokeSession(refreshToken);
      } catch {
        // Local logout is authoritative when server revocation is unavailable.
      }
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      clearNotice: () => setNotice(null),
      isAuthenticated: status === "authenticated",
      login,
      logout,
      notice,
      role: user?.role ?? null,
      status,
      user,
    }),
    [login, logout, notice, status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

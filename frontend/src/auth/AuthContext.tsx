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
  preparePublicDemoWorkspace,
  registerAccount,
  revokeSession,
  type CurrentUser,
  type LoginRequest,
  type RegisterRequest,
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

  const register = useCallback(async (details: RegisterRequest): Promise<void> => {
    await registerAccount(details);
    const tokens = await requestLogin({
      email: details.email,
      password: details.password,
    });
    storeTokenPair(tokens);
    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setNotice(null);
      setStatus("authenticated");
      try {
        await preparePublicDemoWorkspace();
        sessionStorage.removeItem(`fk-demo-setup-retry:${currentUser.id}`);
        sessionStorage.setItem(`fk-demo-onboarding:${currentUser.id}`, "start");
      } catch {
        sessionStorage.setItem(`fk-demo-setup-retry:${currentUser.id}`, "pending");
        setNotice(
          "Your account is ready, but the demo workspace could not be prepared. Please retry from Settings.",
        );
      }
    } catch (error) {
      clearStoredTokens();
      setUser(null);
      setStatus("unauthenticated");
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
      register,
      role: user?.role ?? null,
      status,
      user,
    }),
    [login, logout, notice, register, status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

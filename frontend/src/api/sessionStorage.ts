export interface StoredTokens {
  readonly accessToken: string;
  readonly accessTokenExpiresAt: number;
  readonly refreshToken: string;
}

export interface TokenPair {
  readonly access_token: string;
  readonly expires_in: number;
  readonly refresh_token: string;
  readonly token_type: string;
}

const STORAGE_KEY = "factorymind.auth.tokens";

export function clearStoredTokens(): void {
  window.sessionStorage.removeItem(STORAGE_KEY);
}

export function readStoredTokens(): StoredTokens | null {
  const value = window.sessionStorage.getItem(STORAGE_KEY);
  if (value === null) {
    return null;
  }

  try {
    const parsed = JSON.parse(value) as Partial<StoredTokens>;
    if (
      typeof parsed.accessToken !== "string" ||
      typeof parsed.refreshToken !== "string" ||
      typeof parsed.accessTokenExpiresAt !== "number"
    ) {
      clearStoredTokens();
      return null;
    }
    return parsed as StoredTokens;
  } catch {
    clearStoredTokens();
    return null;
  }
}

// The backend returns both JWTs to JavaScript. Keeping them in sessionStorage
// limits persistence to this tab, but does not protect them from an XSS flaw.
export function storeTokenPair(tokens: TokenPair): StoredTokens {
  const stored: StoredTokens = {
    accessToken: tokens.access_token,
    accessTokenExpiresAt: Date.now() + tokens.expires_in * 1000,
    refreshToken: tokens.refresh_token,
  };
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  return stored;
}

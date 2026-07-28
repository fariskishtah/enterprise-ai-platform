export interface StoredTokens {
  readonly accessToken: string;
  readonly accessTokenExpiresAt: number;
}

export interface TokenPair {
  readonly access_token: string;
  readonly expires_in: number;
  readonly token_type: string;
}

let memoryTokens: StoredTokens | null = null;
let tokenRevision = 0;

export function clearStoredTokens(): void {
  memoryTokens = null;
  tokenRevision += 1;
}

export function readStoredTokens(): StoredTokens | null {
  return memoryTokens;
}

export function storeTokenPair(tokens: TokenPair): StoredTokens {
  const stored: StoredTokens = {
    accessToken: tokens.access_token,
    accessTokenExpiresAt: Date.now() + tokens.expires_in * 1000,
  };
  memoryTokens = stored;
  tokenRevision += 1;
  return stored;
}

export function readTokenRevision(): number {
  return tokenRevision;
}

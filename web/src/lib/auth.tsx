import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, authHeaders, post, refreshSession, setAccessToken } from "./api";
import type { User } from "./types";

// Local auth = email one-time code from the identity service; the session survives reloads through the
// httpOnly refresh cookie. Production: Microsoft Entra External ID via MSAL (ADR-0009) — only this file
// and lib/api.ts should change.

interface AuthState {
  user: User | null;
  loading: boolean;
  requestCode: (email: string) => Promise<{ dev_code?: string }>;
  verifyCode: (email: string, code: string) => Promise<void>;
  signOut: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Restore the session from the refresh cookie, if there is one.
    refreshSession()
      .then((ok) => (ok ? api<User>("/me").then(setUser) : undefined))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const requestCode = useCallback((email: string) => post<{ dev_code?: string }>("/auth/otp/request", { email }), []);

  const verifyCode = useCallback(async (email: string, code: string) => {
    const result = await post<{ access_token: string; user: User }>("/auth/otp/verify", { email, code });
    setAccessToken(result.access_token);
    setUser(result.user);
  }, []);

  const signOut = useCallback(async () => {
    // /auth/* calls don't attach the token automatically (an expired token must not block refresh),
    // so send it explicitly here: the server revokes it rather than just forgetting the cookie.
    await api("/auth/logout", { method: "POST", headers: authHeaders() }).catch(() => undefined);
    setAccessToken(null);
    setUser(null);
  }, []);

  const signOutEverywhere = useCallback(async () => {
    await api("/auth/logout-all", { method: "POST", headers: authHeaders() }).catch(() => undefined);
    setAccessToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, requestCode, verifyCode, signOut, signOutEverywhere }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

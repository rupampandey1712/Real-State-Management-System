// Single API client. All requests go through the gateway at /api.
//
// Auth (ADR-0015): the short-lived access token lives in memory only (never localStorage), so an XSS
// can't read a stored token. The refresh token is an httpOnly cookie scoped to /api/v1/auth; on a 401
// we refresh once and retry. Reloading the page restores the session via the same cookie.

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<(token: string | null) => void>();

export function setAccessToken(token: string | null): void {
  accessToken = token;
  listeners.forEach((listener) => listener(token));
}

export function onAccessTokenChange(listener: (token: string | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: { field: string; issue: string }[] = [],
  ) {
    super(message);
  }
}

export function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

/** Exchanges the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) {
        setAccessToken(null);
        return false;
      }
      const body = (await response.json()) as { access_token: string };
      setAccessToken(body.access_token);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export interface RequestOptions extends RequestInit {
  /** Stable key for unsafe POSTs so a double-click or network retry can't create duplicates. */
  idempotencyKey?: string;
}

async function send(path: string, init: RequestOptions): Promise<Response> {
  const isForm = init.body instanceof FormData;
  const isAuthCall = path.startsWith("/auth/");
  return fetch(`/api/v1${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(isForm || !init.body ? {} : { "Content-Type": "application/json" }),
      ...(isAuthCall ? {} : authHeaders()),
      ...(init.idempotencyKey ? { "Idempotency-Key": init.idempotencyKey } : {}),
      ...init.headers,
    },
  });
}

export async function api<T>(path: string, init: RequestOptions = {}): Promise<T> {
  let response = await send(path, init);
  if (response.status === 401 && accessToken && !path.startsWith("/auth/") && (await refreshSession())) {
    response = await send(path, init); // same idempotency key, so a retried POST is still safe
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = body?.error ?? {};
    throw new ApiError(response.status, error.code ?? "error", error.message ?? "Request failed", error.details);
  }
  return body as T;
}

export const post = <T>(path: string, data?: unknown, options: RequestOptions = {}) =>
  api<T>(path, { ...options, method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });

export const patch = <T>(path: string, data: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(data) });

export const newIdempotencyKey = (): string => crypto.randomUUID();

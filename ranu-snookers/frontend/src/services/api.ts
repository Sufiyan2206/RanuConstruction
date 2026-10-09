/**
 * HTTP client. The access token lives in memory only; the refresh token is an
 * httpOnly cookie (never readable by JS). On 401 we refresh once and retry.
 */
import type { ApiErrorBody, TokenOut } from "@/types/api";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  requestId?: string;
  constructor(status: number, body: Partial<ApiErrorBody["error"]>) {
    super(body.message || `Request failed (${status})`);
    this.status = status;
    this.code = body.code || "HTTP_ERROR";
    this.details = body.details;
    this.requestId = body.request_id;
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<(t: string | null) => void>();

export const tokenStore = {
  get: () => accessToken,
  set(t: string | null) {
    accessToken = t;
    listeners.forEach((l) => l(t));
  },
  subscribe(l: (t: string | null) => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

async function doRefresh(): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/auth/refresh`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (!r.ok) {
      tokenStore.set(null);
      return false;
    }
    const data = (await r.json()) as TokenOut;
    tokenStore.set(data.access_token);
    return true;
  } catch {
    return false;
  }
}

export function refreshSession(): Promise<boolean> {
  if (!refreshing) refreshing = doRefresh().finally(() => (refreshing = null));
  return refreshing;
}

type Opts = { method?: string; body?: unknown; query?: Record<string, unknown>; headers?: Record<string, string>; auth?: boolean; raw?: boolean };

export async function api<T = unknown>(path: string, opts: Opts = {}, retried = false): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  Object.entries(opts.query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  });
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.auth !== false && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let res: Response;
  try {
    res = await fetch(url.toString(), { method: opts.method ?? "GET", headers, credentials: "include", body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  } catch {
    throw new ApiError(0, { code: "NETWORK", message: "Cannot reach the server. Check the internet connection." });
  }
  if (res.status === 401 && opts.auth !== false && !retried && !path.startsWith("/auth/")) {
    if (await refreshSession()) return api<T>(path, opts, true);
  }
  if (opts.raw) return res as unknown as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, (data as ApiErrorBody)?.error ?? { message: res.statusText });
  return data as T;
}

export const get = <T,>(p: string, query?: Record<string, unknown>) => api<T>(p, { query });
export const post = <T,>(p: string, body?: unknown, extra?: Partial<Opts>) => api<T>(p, { method: "POST", body: body ?? {}, ...extra });
export const patch = <T,>(p: string, body?: unknown) => api<T>(p, { method: "PATCH", body });
export const put = <T,>(p: string, body?: unknown) => api<T>(p, { method: "PUT", body });
export const del = <T,>(p: string) => api<T>(p, { method: "DELETE" });

/** Vercel rewrites can proxy HTTP but not WebSockets, so production sets VITE_WS_BASE to the backend's own URL. */
const WS_BASE = import.meta.env.VITE_WS_BASE as string | undefined;

export function wsUrl(path: string): string {
  const base = new URL(WS_BASE || API_BASE, window.location.origin);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  return `${base.toString().replace(/\/$/, "")}${path}`;
}

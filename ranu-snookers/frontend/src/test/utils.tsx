import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { AuthProvider } from "@/stores/auth";
import { ToastProvider } from "@/components/ui";

export type Handler = (url: URL, init?: RequestInit) => { status?: number; body: unknown } | undefined;

/** Route-based fetch mock. Unknown routes → 404 JSON error. */
export function mockFetch(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://localhost");
    const r = handler(url, init);
    const status = r?.status ?? (r ? 200 : 404);
    const body = r ? r.body : { error: { code: "NOT_FOUND", message: `No mock for ${url.pathname}` } };
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function renderWithProviders(ui: ReactElement, { route = "/", path = "*", state }: { route?: string; path?: string; state?: unknown } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[{ pathname: route, state }]}>
            <Routes><Route path={path} element={ui} /></Routes>
          </MemoryRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

export const BRANCH = { id: "b1", code: "MAIN", name: "RANU Main", address: "Main Rd", phone: "1", email: null, timezone: "Asia/Kolkata", currency: "INR", opening_time: "10:00", closing_time: "02:00", is_active: true };
export const GAME = { id: "g1", code: "SNOOKER", name: "Snooker", description: null, default_hourly_rate: "150.00", color: "#146c3a", is_active: true };
export const TABLE = { id: "t1", table_number: 1, name: "Table 1", game_type: GAME, hourly_rate: "150.00", minimum_booking_duration: 30, maximum_booking_duration: 240 };

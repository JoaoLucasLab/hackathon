import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { AppRoutes, routerFuture } from "../routes";

/** Renders the real routes at `route`, with a fresh query cache and no retries. */
export function renderApp(route: string): { queryClient: QueryClient } & ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]} future={routerFuture}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { queryClient, ...render(ui) };
}

export type Handler = (req: Request) => Response | Promise<Response>;

/** A recorded call to the fake backend. */
export interface Call {
  method: string;
  path: string;
  body: unknown;
}

/**
 * Replaces `fetch` with a fake backend. `routes` maps "METHOD /path" to a handler.
 * No test makes a real network call.
 */
export function fakeBackend(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(input, init);
      const path = new URL(req.url).pathname;
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const handler = routes[`${req.method} ${path}`];
      if (!handler) return new Response("not found", { status: 404 });
      return handler(req);
    }),
  );
  return calls;
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

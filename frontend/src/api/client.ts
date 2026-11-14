import createClient from "openapi-fetch";

import type { paths } from "./types";

/** Thrown when the API answers with an error or cannot be reached. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message = `Request failed with status ${status}`,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Backend origin: `VITE_API_BASE_URL`, or same origin (Vite proxies /api in dev). */
export function apiBaseUrl(): string {
  const configured: string | undefined = import.meta.env.VITE_API_BASE_URL;
  return configured ? configured.replace(/\/$/, "") : window.location.origin;
}

/**
 * The typed API client. Paths, bodies and responses all come from the generated
 * OpenAPI types. `credentials: "include"` sends the anonymous `sid` session cookie.
 */
export const api = createClient<paths>({
  baseUrl: apiBaseUrl(),
  credentials: "include",
  // Look `fetch` up on every call, so tests can replace it.
  fetch: (request) => globalThis.fetch(request),
});

/** Unwraps an openapi-fetch result, throwing `ApiError` on any non-2xx answer. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) throw new ApiError(result.response.status);
  return result.data as T;
}

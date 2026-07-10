/**
 * Single typed fetch client for the SPA. Every ADR-029 API-client convention
 * lives here, not in components:
 *  - base `/api/v1/`, single origin, `credentials: same-origin`
 *  - session cookie is the browser credential; no bearer token is sent
 *  - `X-CSRFToken` header on unsafe methods (from the csrftoken cookie)
 *  - `X-Request-ID` propagation for client/server log correlation
 *  - parse the shared error envelope into a typed `ApiError`
 * Retry/polling policy is owned by the TanStack Query client, not here.
 */
import { getCsrfToken } from "./csrf";
import { ApiError, type ApiErrorEnvelope } from "./errors";

export const API_BASE = "/api/v1";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type QueryValue = string | number | boolean | undefined | null;

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

function newRequestId(): string {
  // crypto.randomUUID exists only in secure contexts (HTTPS / localhost). Over
  // plain HTTP (a LAN/dev origin) it is undefined, so fall back to
  // getRandomValues, which is available in insecure contexts and is a CSPRNG
  // (not the Math.random PRNG SonarCloud S2245 flags).
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return `req-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(`${API_BASE}${path}`, globalThis.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return `${url.pathname}${url.search}`;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { "X-Request-ID": newRequestId() };

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (UNSAFE_METHODS.has(method)) {
    headers["X-CSRFToken"] = getCsrfToken();
  }

  const response = await fetch(buildUrl(path, options.query), {
    method,
    headers,
    body,
    credentials: "same-origin",
    signal: options.signal,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : undefined;

  if (!response.ok) {
    const envelope =
      (payload as { error?: ApiErrorEnvelope } | undefined)?.error ??
      ({ code: "error", message: `Request failed (${response.status})` } satisfies ApiErrorEnvelope);
    throw new ApiError(response.status, envelope);
  }

  return payload as T;
}

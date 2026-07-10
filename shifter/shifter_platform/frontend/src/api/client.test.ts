import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { ApiError } from "./errors";

function mockFetch(status: number, body?: unknown) {
  return vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  } as Response);
}

function lastInit(fetchMock: ReturnType<typeof vi.fn>): RequestInit & { headers: Record<string, string> } {
  return fetchMock.mock.calls[0][1] as RequestInit & { headers: Record<string, string> };
}

beforeEach(() => {
  document.cookie = "csrftoken=tok123";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("sends X-CSRFToken and same-origin credentials on unsafe methods", async () => {
    const fetchMock = mockFetch(201, { id: 1 });
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/risks/", { method: "POST", body: { title: "x" } });

    const init = lastInit(fetchMock);
    expect(init.headers["X-CSRFToken"]).toBe("tok123");
    expect(init.credentials).toBe("same-origin");
    expect(init.headers["X-Request-ID"]).toBeTruthy();
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("still sends X-Request-ID when crypto.randomUUID is unavailable (insecure HTTP context)", async () => {
    const fetchMock = mockFetch(200, {});
    vi.stubGlobal("fetch", fetchMock);
    const original = crypto.randomUUID;
    // Simulate a plain-HTTP (non-secure) origin where randomUUID is undefined.
    Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
    try {
      await apiFetch("/risks/");
      expect(lastInit(fetchMock).headers["X-Request-ID"]).toBeTruthy();
    } finally {
      Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true });
    }
  });

  it("does not send CSRF on GET", async () => {
    const fetchMock = mockFetch(200, { results: [] });
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/risks/");

    expect(lastInit(fetchMock).headers["X-CSRFToken"]).toBeUndefined();
  });

  it("parses the shared error envelope into an ApiError", async () => {
    const fetchMock = mockFetch(400, {
      error: { code: "validation_error", message: "Invalid", details: { title: ["Required"] }, request_id: "r-1" },
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiFetch("/risks/", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(400);
    expect(apiError.code).toBe("validation_error");
    expect(apiError.requestId).toBe("r-1");
    expect(apiError.fieldErrors()).toEqual({ title: ["Required"] });
  });

  it("returns undefined on 204 No Content", async () => {
    const fetchMock = mockFetch(204);
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/risks/1/", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("builds a query string and drops undefined params", async () => {
    const fetchMock = mockFetch(200, {});
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/risks/", { query: { severity: "high", page: 2, include_deleted: undefined } });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/v1/risks/?");
    expect(url).toContain("severity=high");
    expect(url).toContain("page=2");
    expect(url).not.toContain("include_deleted");
  });
});

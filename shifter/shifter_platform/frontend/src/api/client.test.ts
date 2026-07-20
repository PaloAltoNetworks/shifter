import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiDownload, apiFetch } from "./client";
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

describe("apiDownload", () => {
  it("preserves unsafe-request protections and returns only a bounded OpenVPN blob", async () => {
    const profile = new TextEncoder().encode("client\nremote vpn.example.test 1194 udp\n");
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      headers: new Headers({ "Content-Type": "application/x-openvpn-profile" }),
      arrayBuffer: async () => profile.buffer,
      text: async () => "",
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    const blob = await apiDownload("/ctf/range/vpn-profile/", {
      method: "POST",
      expectedMediaType: "application/x-openvpn-profile",
      maxBytes: 64 * 1024,
    });

    expect(blob.type).toBe("application/x-openvpn-profile");
    expect(blob.size).toBe(profile.byteLength);
    const init = lastInit(fetchMock);
    expect(init.headers["X-CSRFToken"]).toBe("tok123");
    expect(init.credentials).toBe("same-origin");
    expect(init.headers["X-Request-ID"]).toBeTruthy();
  });

  it("parses JSON error envelopes instead of treating them as profile bytes", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 409,
      ok: false,
      headers: new Headers({ "Content-Type": "application/json" }),
      text: async () => JSON.stringify({ error: { code: "vpn_not_ready", message: "VPN profile is not ready." } }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiDownload("/ctf/range/vpn-profile/", {
      method: "POST",
      expectedMediaType: "application/x-openvpn-profile",
      maxBytes: 64 * 1024,
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("vpn_not_ready");
  });

  it("rejects unexpected media types before exposing response bytes", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      headers: new Headers({ "Content-Type": "text/html" }),
      arrayBuffer: async () => new TextEncoder().encode("not a profile").buffer,
      text: async () => "",
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiDownload("/ctf/range/vpn-profile/", {
        method: "POST",
        expectedMediaType: "application/x-openvpn-profile",
        maxBytes: 64 * 1024,
      }),
    ).rejects.toMatchObject({ code: "unexpected_response" });
  });

  it("rejects an oversized declared content length before reading bytes", async () => {
    const arrayBuffer = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      headers: new Headers({
        "Content-Type": "application/x-openvpn-profile",
        "Content-Length": "5",
      }),
      arrayBuffer,
      text: async () => "",
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiDownload("/ctf/range/vpn-profile/", {
        method: "POST",
        expectedMediaType: "application/x-openvpn-profile",
        maxBytes: 4,
      }),
    ).rejects.toMatchObject({ code: "unexpected_response", message: "The download exceeded the allowed size." });
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it("rejects oversized response bytes when content length is absent", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      headers: new Headers({ "Content-Type": "application/x-openvpn-profile" }),
      arrayBuffer: async () => new Uint8Array(5).buffer,
      text: async () => "",
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiDownload("/ctf/range/vpn-profile/", {
        method: "POST",
        expectedMediaType: "application/x-openvpn-profile",
        maxBytes: 4,
      }),
    ).rejects.toMatchObject({ code: "unexpected_response", message: "The download exceeded the allowed size." });
  });
});

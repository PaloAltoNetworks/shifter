import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";

import { ApiError } from "@/api/errors";
import type { GuacamoleBootstrapQueued, GuacamoleBootstrapStatus } from "@/api/types";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { useGuacamoleSession, useNgfwSshSession } from "./guacamole";

const mockApi = vi.mocked(apiFetch);

const QUEUED: GuacamoleBootstrapQueued = {
  request_id: "33333333-3333-3333-3333-333333333333",
  status: "PENDING",
  status_url: "/api/v1/mission-control/guacamole/bootstrap/33333333-3333-3333-3333-333333333333/",
  url: "",
};

const SIGNED_URL = "https://guac.example.test/session/abc?token=SECRET";

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function renderSession() {
  return renderHook(() => useGuacamoleSession(), { wrapper });
}

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockApi.mockReset();
  openSpy = vi.fn();
  vi.stubGlobal("open", openSpy);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useGuacamoleSession", () => {
  it("starts idle with no pending protocol or error", () => {
    const { result } = renderSession();
    expect(result.current.state).toBe("idle");
    expect(result.current.pendingProtocol).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("queues, polls to SUCCEEDED, and opens the signed URL in a new tab", async () => {
    const status: GuacamoleBootstrapStatus = { request_id: QUEUED.request_id, status: "SUCCEEDED", url: SIGNED_URL };
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/ssh-url/")) return Promise.resolve(QUEUED);
      if (path === `/mission-control/guacamole/bootstrap/${QUEUED.request_id}/`) return Promise.resolve(status);
      throw new Error(`unexpected path ${path}`);
    });

    const { result } = renderSession();
    act(() => result.current.open({ protocol: "ssh", instanceUuid: "instance-1" }));

    expect(result.current.pendingProtocol).toBe("ssh");
    expect(result.current.state).toBe("preparing");

    await waitFor(() => expect(result.current.state).toBe("idle"));

    expect(mockApi).toHaveBeenCalledWith("/mission-control/guacamole/ssh-url/", {
      method: "POST",
      body: { instance_uuid: "instance-1" },
    });
    expect(openSpy).toHaveBeenCalledWith(SIGNED_URL, "_blank", "noopener,noreferrer");
    expect(result.current.pendingProtocol).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("never logs or otherwise surfaces the signed URL beyond window.open", async () => {
    const status: GuacamoleBootstrapStatus = { request_id: QUEUED.request_id, status: "SUCCEEDED", url: SIGNED_URL };
    mockApi.mockImplementation((path: string) =>
      path.endsWith("/rdp-url/") ? Promise.resolve(QUEUED) : Promise.resolve(status),
    );
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { result } = renderSession();
    act(() => result.current.open({ protocol: "rdp", instanceUuid: "instance-1" }));
    await waitFor(() => expect(result.current.state).toBe("idle"));

    for (const spy of [logSpy, warnSpy, errorSpy]) {
      for (const call of spy.mock.calls) {
        expect(call.join(" ")).not.toContain(SIGNED_URL);
      }
    }
    expect(result.current.error).toBeNull();
    logSpy.mockRestore();
    warnSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it("surfaces the bootstrap request failure and never calls window.open", async () => {
    mockApi.mockRejectedValue(new ApiError(503, { code: "error", message: "SSH service not configured" }));

    const { result } = renderSession();
    act(() => result.current.open({ protocol: "ssh", instanceUuid: "instance-1" }));

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.error).toBe("SSH service not configured");
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("surfaces a FAILED bootstrap status and never calls window.open", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/ssh-url/")) return Promise.resolve(QUEUED);
      return Promise.resolve({
        request_id: QUEUED.request_id,
        status: "FAILED",
        error: "No SSH key configured",
      } satisfies GuacamoleBootstrapStatus);
    });

    const { result } = renderSession();
    act(() => result.current.open({ protocol: "ssh", instanceUuid: "instance-1" }));

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.error).toBe("No SSH key configured");
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("times out after the bounded poll attempts without ever calling window.open", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/ssh-url/")) return Promise.resolve(QUEUED);
      return Promise.resolve({ request_id: QUEUED.request_id, status: "PENDING" } satisfies GuacamoleBootstrapStatus);
    });

    const { result } = renderSession();
    act(() => result.current.open({ protocol: "ssh", instanceUuid: "instance-1" }));

    // 60 attempts * 1s poll interval, plus slack.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });

    expect(result.current.state).toBe("error");
    expect(result.current.error).toBe("SSH session request timed out");
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("ignores a second open() call while one is already in flight (no concurrent bootstraps)", async () => {
    let resolvePost!: (value: GuacamoleBootstrapQueued) => void;
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/ssh-url/")) {
        return new Promise((resolve) => {
          resolvePost = resolve;
        });
      }
      return Promise.resolve({ request_id: QUEUED.request_id, status: "SUCCEEDED", url: SIGNED_URL } satisfies GuacamoleBootstrapStatus);
    });

    const { result } = renderSession();
    act(() => result.current.open({ protocol: "ssh", instanceUuid: "instance-1" }));
    act(() => result.current.open({ protocol: "ssh", instanceUuid: "instance-1" }));

    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));

    await act(async () => {
      resolvePost(QUEUED);
    });
    await waitFor(() => expect(result.current.state).toBe("idle"));
    expect(openSpy).toHaveBeenCalledTimes(1);
  });
});

describe("useNgfwSshSession", () => {
  function renderNgfwSession() {
    return renderHook(() => useNgfwSshSession(), { wrapper });
  }

  it("starts idle with no error", () => {
    const { result } = renderNgfwSession();
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBeNull();
  });

  it("queues via the app-id-keyed ssh-url endpoint, polls, and opens the signed URL", async () => {
    const status: GuacamoleBootstrapStatus = { request_id: QUEUED.request_id, status: "SUCCEEDED", url: SIGNED_URL };
    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/ngfw/ngfw-app-1/ssh-url/") return Promise.resolve(QUEUED);
      if (path === `/mission-control/guacamole/bootstrap/${QUEUED.request_id}/`) return Promise.resolve(status);
      throw new Error(`unexpected path ${path}`);
    });

    const { result } = renderNgfwSession();
    act(() => result.current.open("ngfw-app-1"));

    expect(result.current.state).toBe("preparing");
    await waitFor(() => expect(result.current.state).toBe("idle"));

    expect(mockApi).toHaveBeenCalledWith("/mission-control/ngfw/ngfw-app-1/ssh-url/", { method: "POST" });
    expect(openSpy).toHaveBeenCalledWith(SIGNED_URL, "_blank", "noopener,noreferrer");
    expect(result.current.error).toBeNull();
  });

  it("surfaces the bootstrap request failure and never calls window.open", async () => {
    mockApi.mockRejectedValue(new ApiError(503, { code: "error", message: "SSH service not configured" }));

    const { result } = renderNgfwSession();
    act(() => result.current.open("ngfw-app-1"));

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.error).toBe("SSH service not configured");
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("surfaces a FAILED bootstrap status without auto-retrying", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/ssh-url/")) return Promise.resolve(QUEUED);
      return Promise.resolve({
        request_id: QUEUED.request_id,
        status: "FAILED",
        error: "NGFW is not reachable",
      } satisfies GuacamoleBootstrapStatus);
    });

    const { result } = renderNgfwSession();
    act(() => result.current.open("ngfw-app-1"));

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.error).toBe("NGFW is not reachable");
    const sshCalls = mockApi.mock.calls.filter(([path]) => (path as string).endsWith("/ssh-url/"));
    expect(sshCalls).toHaveLength(1);
  });

  it("ignores a second open() call while one is already in flight", async () => {
    let resolvePost!: (value: GuacamoleBootstrapQueued) => void;
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/ssh-url/")) {
        return new Promise((resolve) => {
          resolvePost = resolve;
        });
      }
      return Promise.resolve({ request_id: QUEUED.request_id, status: "SUCCEEDED", url: SIGNED_URL } satisfies GuacamoleBootstrapStatus);
    });

    const { result } = renderNgfwSession();
    act(() => result.current.open("ngfw-app-1"));
    act(() => result.current.open("ngfw-app-1"));

    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));

    await act(async () => {
      resolvePost(QUEUED);
    });
    await waitFor(() => expect(result.current.state).toBe("idle"));
    expect(openSpy).toHaveBeenCalledTimes(1);
  });
});

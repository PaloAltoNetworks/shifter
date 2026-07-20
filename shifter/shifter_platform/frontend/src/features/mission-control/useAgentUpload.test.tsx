import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";

import { ApiError } from "@/api/errors";
import type { UploadCompleteResponse, UploadInitiateResponse } from "@/api/types";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

vi.mock("./upload", () => ({ uploadFileToPresignedUrl: vi.fn() }));

import { uploadFileToPresignedUrl } from "./upload";

import { useAgentUpload } from "./useAgentUpload";

const mockApi = vi.mocked(apiFetch);
const mockUpload = vi.mocked(uploadFileToPresignedUrl);

const INITIATED: UploadInitiateResponse = {
  presigned_url: "https://s3.example.test/put?sig=abc",
  s3_key: "agents/agent.zip",
  upload_token: "token-123",
  expected_os: "linux",
};

const COMPLETED: UploadCompleteResponse = { success: true, agent_id: 7, message: "Agent 'kali' uploaded." };

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function renderUpload() {
  return renderHook(() => useAgentUpload(), { wrapper });
}

function file(sizeBytes = 10): File {
  return new File([new Uint8Array(sizeBytes)], "agent.zip");
}

beforeEach(() => {
  mockApi.mockReset();
  mockUpload.mockReset();
});

describe("useAgentUpload", () => {
  it("starts idle with no progress or error", () => {
    const { result } = renderUpload();
    expect(result.current.phase).toBe("idle");
    expect(result.current.progress).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("rejects an empty name without calling the API", () => {
    const { result } = renderUpload();
    act(() => result.current.start({ name: "  ", file: file(), agentType: "xdr" }));

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toBe("Agent name is required.");
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("rejects a file over the 2048 MB limit without calling the API", () => {
    const { result } = renderUpload();
    const oversized = { name: "agent.zip", size: (2048 + 1) * 1024 * 1024 } as File;
    act(() => result.current.start({ name: "kali-agent", file: oversized, agentType: "xdr" }));

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toContain("2048 MB");
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("runs initiate -> presigned PUT (with progress) -> complete, then returns to idle", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/upload/initiate/") return Promise.resolve(INITIATED);
      if (path === "/mission-control/upload/complete/") return Promise.resolve(COMPLETED);
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    let reportProgress: (percent: number) => void = () => {};
    let resolvePut: () => void = () => {};
    mockUpload.mockImplementation((_url, _file, onProgress) => {
      reportProgress = onProgress;
      return { promise: new Promise<void>((resolve) => (resolvePut = resolve)), abort: vi.fn() };
    });

    const { result } = renderUpload();
    act(() => result.current.start({ name: "kali-agent", file: file(), agentType: "xdr" }));

    expect(result.current.phase).toBe("uploading");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/upload/initiate/", {
        method: "POST",
        body: { name: "kali-agent", filename: "agent.zip", file_size: 10, agent_type: "xdr" },
      }),
    );

    act(() => reportProgress(42));
    expect(result.current.progress).toBe(42);

    await act(async () => resolvePut());

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/upload/complete/", {
        method: "POST",
        body: { upload_token: "token-123" },
      }),
    );
    await waitFor(() => expect(result.current.phase).toBe("idle"));
    expect(result.current.progress).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("surfaces an initiate failure without auto-retrying or starting the PUT", async () => {
    mockApi.mockRejectedValue(new ApiError(409, { code: "conflict", message: "An upload is already in progress." }));

    const { result } = renderUpload();
    act(() => result.current.start({ name: "kali-agent", file: file(), agentType: "xdr" }));

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toBe("An upload is already in progress.");
    expect(mockUpload).not.toHaveBeenCalled();
    expect(mockApi).toHaveBeenCalledTimes(1);
  });

  it("surfaces a presigned PUT failure and cleans up the upload session server-side", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/upload/initiate/") return Promise.resolve(INITIATED);
      if (path === "/mission-control/upload/cancel/") return Promise.resolve({ success: true });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    mockUpload.mockReturnValue({ promise: Promise.reject(new Error("Network error during upload")), abort: vi.fn() });

    const { result } = renderUpload();
    act(() => result.current.start({ name: "kali-agent", file: file(), agentType: "xdr" }));

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toBe("Network error during upload");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/upload/cancel/", {
        method: "POST",
        body: { upload_token: "token-123" },
      }),
    );
  });

  it("cancel() aborts the in-flight PUT and returns to idle without completing", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/upload/initiate/") return Promise.resolve(INITIATED);
      if (path === "/mission-control/upload/cancel/") return Promise.resolve({ success: true });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    const abort = vi.fn();
    mockUpload.mockReturnValue({ promise: new Promise<void>(() => {}), abort });

    const { result } = renderUpload();
    act(() => result.current.start({ name: "kali-agent", file: file(), agentType: "xdr" }));
    await waitFor(() => expect(mockUpload).toHaveBeenCalled());

    act(() => result.current.cancel());

    expect(abort).toHaveBeenCalled();
    expect(result.current.phase).toBe("idle");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/upload/cancel/", {
        method: "POST",
        body: { upload_token: "token-123" },
      }),
    );
    const completeCalls = mockApi.mock.calls.filter(([path]) => path === "/mission-control/upload/complete/");
    expect(completeCalls).toHaveLength(0);
  });
});

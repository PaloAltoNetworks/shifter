import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { AgentListResponse, UploadCompleteResponse, UploadInitiateResponse } from "@/api/types";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

vi.mock("./upload", () => ({ uploadFileToPresignedUrl: vi.fn() }));

import { uploadFileToPresignedUrl } from "./upload";

import { AgentsPage } from "./AgentsPage";

const mockApi = vi.mocked(apiFetch);
const mockUpload = vi.mocked(uploadFileToPresignedUrl);

const AGENTS: AgentListResponse = {
  agents: [
    {
      id: 5,
      name: "kali-agent",
      os_name: "Kali Linux",
      os_slug: "kali",
      file_size_mb: 12.3,
      original_filename: "kali.tar.gz",
      created_at: "2026-07-01T00:00:00Z",
      agent_type: "xdr",
      agent_type_display: "XDR/XSIAM Agent",
    },
  ],
  max_file_size_bytes: 2048 * 1024 * 1024,
};

const INITIATED: UploadInitiateResponse = {
  presigned_url: "https://s3.example.test/put?sig=abc",
  s3_key: "agents/agent.zip",
  upload_token: "token-123",
  expected_os: "linux",
};

const COMPLETED: UploadCompleteResponse = { success: true, agent_id: 9, message: "Agent uploaded." };

function selectAgentsList() {
  mockApi.mockImplementation((path: string) => {
    if (path === "/mission-control/agents/") return Promise.resolve(AGENTS);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function agentFile(name = "agent.zip", sizeBytes = 10): File {
  return new File([new Uint8Array(sizeBytes)], name);
}

beforeEach(() => {
  mockApi.mockReset();
  mockUpload.mockReset();
});

describe("AgentsPage", () => {
  it("shows a loading skeleton while agents load", () => {
    mockApi.mockReturnValue(new Promise(() => {}));
    const { container } = renderRoute(<AgentsPage />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("shows an error when agents fail to load", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<AgentsPage />);
    expect(await screen.findByText("Could not load your agents")).toBeInTheDocument();
  });

  it("shows an empty state when there are no agents", async () => {
    mockApi.mockResolvedValue({
      agents: [],
      max_file_size_bytes: 2048 * 1024 * 1024,
    } satisfies AgentListResponse);
    renderRoute(<AgentsPage />);
    expect(await screen.findByText("No agents uploaded yet")).toBeInTheDocument();
  });

  it("lists agents with no delete action and notes the deletion gap", async () => {
    selectAgentsList();
    renderRoute(<AgentsPage />);

    expect(await screen.findByText("kali-agent")).toBeInTheDocument();
    const row = screen.getByText("kali-agent").closest("tr");
    if (!row) throw new Error("expected an agent row");
    expect(within(row).getByText("XDR/XSIAM Agent")).toBeInTheDocument();
    expect(within(row).getByText("Kali Linux")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(screen.getByText("Agent deletion is not yet available here")).toBeInTheDocument();
    expect(screen.getByText(/#1328, #1329/)).toBeInTheDocument();
  });

  it("shows the per-file limit derived from the server-owned agent-list response", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/agents/") {
        return Promise.resolve({ agents: [], max_file_size_bytes: 512 * 1024 * 1024 } satisfies AgentListResponse);
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    renderRoute(<AgentsPage />);

    expect(await screen.findByText("Max 512 MB per file.")).toBeInTheDocument();
  });

  it("disables submit until a name and file are provided", async () => {
    selectAgentsList();
    const user = userEvent.setup();
    renderRoute(<AgentsPage />);

    const submit = await screen.findByRole("button", { name: "Upload agent" });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("Agent name"), "kali-agent");
    expect(submit).toBeDisabled();

    const fileInput = screen.getByLabelText("Installer file");
    await user.upload(fileInput, agentFile());
    expect(submit).toBeEnabled();
  });

  it("uploads via initiate -> presigned PUT (with progress) -> complete", async () => {
    selectAgentsList();
    let reportProgress: (percent: number) => void = () => {};
    let resolvePut: () => void = () => {};
    mockUpload.mockImplementation((_url, _file, onProgress) => {
      reportProgress = onProgress;
      return { promise: new Promise<void>((resolve) => (resolvePut = resolve)), abort: vi.fn() };
    });

    const user = userEvent.setup();
    renderRoute(<AgentsPage />);

    await user.type(await screen.findByLabelText("Agent name"), "kali-agent");
    await user.upload(screen.getByLabelText("Installer file"), agentFile());

    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/agents/") return Promise.resolve(AGENTS);
      if (path === "/mission-control/upload/initiate/") return Promise.resolve(INITIATED);
      if (path === "/mission-control/upload/complete/") return Promise.resolve(COMPLETED);
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    await user.click(screen.getByRole("button", { name: "Upload agent" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/upload/initiate/", {
        method: "POST",
        body: { name: "kali-agent", filename: "agent.zip", file_size: 10, agent_type: "xdr" },
      }),
    );

    act(() => reportProgress(50));
    expect(await screen.findByText(/50%/)).toBeInTheDocument();

    await act(async () => resolvePut());

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/upload/complete/", {
        method: "POST",
        body: { upload_token: "token-123" },
      }),
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "Upload agent" })).toBeDisabled());
  });

  it("shows a server error at initiate without retrying automatically", async () => {
    selectAgentsList();
    const user = userEvent.setup();
    renderRoute(<AgentsPage />);

    await user.type(await screen.findByLabelText("Agent name"), "kali-agent");
    await user.upload(screen.getByLabelText("Installer file"), agentFile());

    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/agents/") return Promise.resolve(AGENTS);
      if (path === "/mission-control/upload/initiate/") {
        return Promise.reject(new ApiError(409, { code: "conflict", message: "An upload is already in progress." }));
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    await user.click(screen.getByRole("button", { name: "Upload agent" }));

    expect(await screen.findByText("An upload is already in progress.")).toBeInTheDocument();
    const initiateCalls = mockApi.mock.calls.filter(([path]) => path === "/mission-control/upload/initiate/");
    expect(initiateCalls).toHaveLength(1);
    expect(mockUpload).not.toHaveBeenCalled();
  });

  it("cancels an in-flight upload without completing it", async () => {
    selectAgentsList();
    const abort = vi.fn();
    mockUpload.mockReturnValue({ promise: new Promise<void>(() => {}), abort });

    const user = userEvent.setup();
    renderRoute(<AgentsPage />);

    await user.type(await screen.findByLabelText("Agent name"), "kali-agent");
    await user.upload(screen.getByLabelText("Installer file"), agentFile());

    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/agents/") return Promise.resolve(AGENTS);
      if (path === "/mission-control/upload/initiate/") return Promise.resolve(INITIATED);
      if (path === "/mission-control/upload/cancel/") return Promise.resolve({ success: true });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    await user.click(screen.getByRole("button", { name: "Upload agent" }));
    await waitFor(() => expect(mockUpload).toHaveBeenCalled());

    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(abort).toHaveBeenCalled();
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/upload/cancel/", {
        method: "POST",
        body: { upload_token: "token-123" },
      }),
    );
    const completeCalls = mockApi.mock.calls.filter(([path]) => path === "/mission-control/upload/complete/");
    expect(completeCalls).toHaveLength(0);
  });

  it("has no axe violations once agents are loaded", async () => {
    selectAgentsList();
    const { container } = renderRoute(<AgentsPage />);
    await screen.findByText("kali-agent");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

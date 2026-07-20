import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen } from "@testing-library/react";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { CtfWorkspaceLayout } from "./CtfWorkspaceLayout";

const mockApi = vi.mocked(apiFetch);

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    // No-op for tests.
  }
}

beforeEach(() => {
  mockApi.mockReset();
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const CURRENT_EVENT = {
  event: { id: "e1", name: "Spring CTF", status: "active" },
  participant: { id: "p1", name: "Alice", status: "active" },
};

describe("CtfWorkspaceLayout", () => {
  it("subscribes to the event topic and toasts incoming notifications", async () => {
    mockApi.mockResolvedValue(CURRENT_EVENT);
    renderRoute(<CtfWorkspaceLayout />);

    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    expect(socket.url).toContain("/ws/notifications/");

    act(() => socket.onopen?.());
    expect(socket.sent[0]).toContain("ctf:event:e1");

    act(() =>
      socket.onmessage?.({
        data: JSON.stringify({
          type: "notification",
          payload: { kind: "first_blood", challenge_name: "Web 100", participant_name: "Bob" },
        }),
      }),
    );
    expect(await screen.findByText("First blood!")).toBeInTheDocument();
    expect(screen.getByText(/Bob drew first blood on Web 100/)).toBeInTheDocument();
  });

  it("ignores malformed frames", async () => {
    mockApi.mockResolvedValue(CURRENT_EVENT);
    renderRoute(<CtfWorkspaceLayout />);
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => socket.onmessage?.({ data: "not-json" }));
    expect(screen.queryByText("First blood!")).not.toBeInTheDocument();
  });
});

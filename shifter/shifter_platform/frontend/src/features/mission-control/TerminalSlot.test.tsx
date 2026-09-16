import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { InstancePresentation } from "@/api/types";
import { activeSockets, FakeWebSocket, installFakeWebSocket, latestSocket } from "@/test/fake-websocket";

function allSockets(): FakeWebSocket[] {
  return FakeWebSocket.instances;
}

const openGuacamole = vi.fn();
let guacamoleError: string | null = null;
let pendingProtocol: "rdp" | "ssh" | null = null;

vi.mock("./guacamole", () => ({
  useGuacamoleSession: () => ({
    pendingProtocol,
    state: guacamoleError ? "error" : "idle",
    error: guacamoleError,
    open: openGuacamole,
  }),
}));

vi.mock("@xterm/addon-fit", () => {
  class FakeFitAddon {
    fit = vi.fn();
  }
  return { FitAddon: FakeFitAddon };
});

vi.mock("@xterm/xterm", () => {
  class FakeXTerm {
    cols = 80;
    rows = 24;
    open = vi.fn();
    loadAddon = vi.fn();
    write = vi.fn();
    focus = vi.fn();
    dispose = vi.fn();
    element = document.createElement("div");
    getSelection = vi.fn(() => "");
    paste = vi.fn();
    attachCustomKeyEventHandler = vi.fn();
    onData() {
      return { dispose: vi.fn() };
    }
    onResize() {
      return { dispose: vi.fn() };
    }
  }
  return { Terminal: FakeXTerm };
});

import { TerminalSlot } from "./TerminalSlot";
import type { ConsoleTarget } from "./consoleTargets";

function target(overrides: Partial<InstancePresentation> = {}): ConsoleTarget {
  return {
    uuid: "11111111-1111-1111-1111-111111111111",
    name: "web-01",
    role: "victim",
    os_type: "ubuntu",
    join_domain: false,
    ami_key: null,
    private_ip: "10.0.1.10",
    ...overrides,
  } as ConsoleTarget;
}

let restoreWebSocket: () => void;

beforeEach(() => {
  restoreWebSocket = installFakeWebSocket();
  openGuacamole.mockClear();
  guacamoleError = null;
  pendingProtocol = null;
});

afterEach(() => {
  restoreWebSocket();
});

describe("TerminalSlot", () => {
  it("opens one terminal socket for its assigned target", () => {
    render(<TerminalSlot target={target()} label="Pane" />);
    expect(latestSocket().url).toContain("/ws/terminal/11111111-1111-1111-1111-111111111111/");
  });

  it("identifies the device by name and private IP as text, not color", () => {
    render(<TerminalSlot target={target({ name: "win-dc01", private_ip: "10.0.1.20" })} label="Pane" />);
    expect(screen.getByText("win-dc01")).toBeInTheDocument();
    expect(screen.getByText("10.0.1.20")).toBeInTheDocument();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
  });

  it("delegates RDP to the shared server-brokered opener rather than building a URL", async () => {
    const user = userEvent.setup();
    render(<TerminalSlot target={target()} label="Pane" />);

    await user.click(screen.getByRole("button", { name: /open rdp session/i }));

    expect(openGuacamole).toHaveBeenCalledWith({
      protocol: "rdp",
      instanceUuid: "11111111-1111-1111-1111-111111111111",
    });
  });

  it("surfaces a Guacamole failure to the user without exposing a signed URL", () => {
    guacamoleError = "RDP session request timed out";
    render(<TerminalSlot target={target()} label="Pane" />);
    expect(screen.getByRole("alert")).toHaveTextContent("RDP session request timed out");
  });

  it("never reconnects on its own after a retryable capacity close (4503)", async () => {
    render(<TerminalSlot target={target()} label="Pane" />);
    const socketsBeforeClose = allSockets().length;

    act(() => latestSocket().emitClose(4503, "terminal capacity"));

    expect(screen.getByText(/Terminal capacity is temporarily unavailable/)).toBeInTheDocument();
    // A saturated worker must not be hammered: no socket is opened until the
    // user asks for one.
    expect(allSockets()).toHaveLength(socketsBeforeClose);
    expect(activeSockets()).toHaveLength(0);
  });

  it("opens a fresh socket only when the user clicks reconnect", async () => {
    const user = userEvent.setup();
    render(<TerminalSlot target={target()} label="Pane" />);
    act(() => latestSocket().emitClose(4503, "terminal capacity"));
    const socketsBeforeClick = allSockets().length;

    await user.click(screen.getByRole("button", { name: /reconnect/i }));

    expect(allSockets().length).toBe(socketsBeforeClick + 1);
    expect(activeSockets()).toHaveLength(1);
    expect(screen.queryByText(/Terminal capacity is temporarily unavailable/)).not.toBeInTheDocument();
  });

  it("renders an empty-pane message and opens no socket when no target is assigned", () => {
    render(<TerminalSlot target={null} label="Right pane" />);
    expect(screen.getByText(/no device selected/i)).toBeInTheDocument();
    expect(() => latestSocket()).toThrow();
  });
});

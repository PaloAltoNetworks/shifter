import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { installFakeWebSocket, latestSocket } from "@/test/fake-websocket";
import { renderRoute } from "@/test/utils";

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
    onData() {
      return { dispose: vi.fn() };
    }
    onResize() {
      return { dispose: vi.fn() };
    }
  }
  return { Terminal: FakeXTerm };
});

import { TerminalPage } from "./TerminalPage";

const INSTANCE_UUID = "22222222-2222-2222-2222-222222222222";

function renderTerminalPage() {
  return renderRoute(<TerminalPage />, {
    path: "/mission-control/terminal/:instanceUuid",
    initialEntries: [`/mission-control/terminal/${INSTANCE_UUID}`],
  });
}

beforeEach(() => {
  installFakeWebSocket();
});

describe("TerminalPage", () => {
  it("opens the terminal socket for the :instanceUuid route param", () => {
    renderTerminalPage();
    expect(latestSocket().url).toBe(`ws://${window.location.host}/ws/terminal/${INSTANCE_UUID}/`);
  });

  it("shows a connecting badge, then a connected badge once the socket opens", () => {
    renderTerminalPage();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();

    act(() => latestSocket().emitOpen());
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("shows a non-destructive 'session ended' banner on a clean close (code 1000)", () => {
    renderTerminalPage();
    act(() => latestSocket().emitClose(1000, "client closing"));

    expect(screen.getByText("Session ended.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
  });

  it("maps SSH_CONNECTION_FAILED (4502) to accessible copy in a destructive banner", () => {
    renderTerminalPage();
    act(() => latestSocket().emitClose(4502, "ssh failed"));

    expect(screen.getByText("Could not establish an SSH connection to this instance.")).toBeInTheDocument();
  });

  it("maps an unrecognized close code to a generic message", () => {
    renderTerminalPage();
    act(() => latestSocket().emitClose(1006, "abnormal"));
    expect(screen.getByText("Connection closed unexpectedly.")).toBeInTheDocument();
  });

  it("reconnecting opens a fresh socket and clears the closed banner", async () => {
    renderTerminalPage();
    const first = latestSocket();
    act(() => first.emitClose(4503, "capacity"));
    expect(screen.getByText(/Terminal capacity is temporarily unavailable/)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Reconnect" }));

    expect(screen.queryByText(/Terminal capacity is temporarily unavailable/)).not.toBeInTheDocument();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
    expect(latestSocket()).not.toBe(first);
  });

  it("does not crash and shows a fallback when the route has no instanceUuid", () => {
    renderRoute(<TerminalPage />);
    expect(screen.getByText("No instance specified")).toBeInTheDocument();
  });

  it("has no axe violations while connected", async () => {
    const { container } = renderTerminalPage();
    act(() => latestSocket().emitOpen());
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("has no axe violations on the closed/reconnect banner", async () => {
    const { container } = renderTerminalPage();
    act(() => latestSocket().emitClose(4502, "ssh failed"));
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

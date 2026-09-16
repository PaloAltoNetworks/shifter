import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { CurrentRangeResponse, InstancePresentation, RangePresentation } from "@/api/types";
import { activeSockets, installFakeWebSocket } from "@/test/fake-websocket";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiDownload: vi.fn(), apiFetch: vi.fn() }));

const openGuacamole = vi.fn();
vi.mock("./guacamole", () => ({
  useGuacamoleSession: () => ({ pendingProtocol: null, state: "idle", error: null, open: openGuacamole }),
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

import { apiFetch } from "@/api/client";

import { TerminalWorkspacePage } from "./TerminalWorkspacePage";

const mockApi = vi.mocked(apiFetch);
let restoreWebSocket: () => void;

function instance(overrides: Partial<InstancePresentation> = {}): InstancePresentation {
  return {
    uuid: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    name: "kali-01",
    role: "attacker",
    os_type: "kali",
    join_domain: false,
    ami_key: "kali",
    private_ip: "10.0.0.5",
    ...overrides,
  } as InstancePresentation;
}

const KALI = instance();
const WIN = instance({ uuid: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", name: "win-dc01", private_ip: "10.0.0.6" });
const WEB = instance({ uuid: "cccccccc-cccc-cccc-cccc-cccccccccccc", name: "web-01", private_ip: "10.0.0.7" });

function currentRange(overrides: Partial<RangePresentation> = {}): CurrentRangeResponse {
  return {
    has_range: true,
    range: {
      request_id: "11111111-1111-1111-1111-111111111111",
      range_id: 42,
      scenario_id: "basic",
      user_id: 7,
      status: "ready",
      instances: [KALI, WIN],
      agent_name: "agent-1",
      range_type: "demo",
      is_ready: true,
      is_terminal: false,
      is_active: true,
      ...overrides,
    },
    connection_urls: [],
    raes_projection: null,
    raes_participant_runtime: null,
    lifecycle: null,
    vpn_profile_available: false,
  } as CurrentRangeResponse;
}

function renderWorkspace(path = "/mission-control/terminal/") {
  return renderRoute(<TerminalWorkspacePage />, {
    path: "/mission-control/terminal/:instanceUuid?",
    initialEntries: [path],
  });
}

beforeEach(() => {
  restoreWebSocket = installFakeWebSocket();
  mockApi.mockReset();
  openGuacamole.mockClear();
  globalThis.localStorage.clear();
});

afterEach(() => {
  restoreWebSocket();
});

describe("TerminalWorkspacePage", () => {
  it("lists every console-capable instance of the active range as a tab", async () => {
    mockApi.mockResolvedValue(currentRange({ instances: [KALI, WIN, WEB] }));
    renderWorkspace();

    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining("kali-01"), expect.stringContaining("win-dc01")]),
    );
    expect(tabs).toHaveLength(3);
  });

  it("excludes NGFW rows, which are reached through the NGFW surface instead", async () => {
    const ngfw = instance({ uuid: "dddddddd-dddd-dddd-dddd-dddddddddddd", name: "fw-01", role: "ngfw" });
    mockApi.mockResolvedValue(currentRange({ instances: [KALI, ngfw] }));
    renderWorkspace();

    await screen.findAllByRole("tab");
    expect(screen.queryByText("fw-01")).not.toBeInTheDocument();
  });

  it("opens exactly one terminal socket in tabs mode", async () => {
    mockApi.mockResolvedValue(currentRange({ instances: [KALI, WIN, WEB] }));
    renderWorkspace();

    await screen.findAllByRole("tab");
    await waitFor(() => expect(activeSockets()).toHaveLength(1));
  });

  it("switches the connected device when another tab is selected, without leaking the old socket", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue(currentRange());
    renderWorkspace();

    await waitFor(() => expect(activeSockets()).toHaveLength(1));
    expect(activeSockets()[0].url).toContain(KALI.uuid as string);

    await user.click(screen.getByRole("tab", { name: /win-dc01/ }));

    await waitFor(() => expect(activeSockets()).toHaveLength(1));
    expect(activeSockets()[0].url).toContain(WIN.uuid as string);
  });

  it("shows two distinct devices side by side in split mode", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue(currentRange());
    renderWorkspace();

    await screen.findAllByRole("tab");
    await user.click(screen.getByRole("button", { name: /split/i }));

    await waitFor(() => expect(activeSockets()).toHaveLength(2));
    const urls = activeSockets().map((socket) => socket.url);
    expect(urls.some((url) => url.includes(KALI.uuid as string))).toBe(true);
    expect(urls.some((url) => url.includes(WIN.uuid as string))).toBe(true);
  });

  it("persists the layout choice across a remount", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue(currentRange());
    const first = renderWorkspace();

    await screen.findAllByRole("tab");
    await user.click(screen.getByRole("button", { name: /split/i }));
    await waitFor(() => expect(activeSockets()).toHaveLength(2));
    first.unmount();

    renderWorkspace();
    await waitFor(() => expect(activeSockets()).toHaveLength(2));
    expect(globalThis.localStorage.getItem("terminal-layout")).toBe("split");
  });

  it("selects a deep-linked instance as the active tab", async () => {
    mockApi.mockResolvedValue(currentRange());
    renderWorkspace(`/mission-control/terminal/${WIN.uuid}/`);

    await waitFor(() => expect(activeSockets()).toHaveLength(1));
    expect(activeSockets()[0].url).toContain(WIN.uuid as string);
  });

  it("follows the deep link when the route changes while the workspace stays mounted", async () => {
    mockApi.mockResolvedValue(currentRange());
    const router = createMemoryRouter(
      [{ path: "/mission-control/terminal/:instanceUuid?", element: <TerminalWorkspacePage /> }],
      { initialEntries: [`/mission-control/terminal/${KALI.uuid}/`] },
    );
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(activeSockets()).toHaveLength(1));
    expect(activeSockets()[0].url).toContain(KALI.uuid as string);

    // Client-side navigation to another deep link (in-app link, back/forward)
    // must retarget the pane, not keep showing the previous device.
    await act(() => router.navigate(`/mission-control/terminal/${WIN.uuid}/`));

    await waitFor(() => expect(activeSockets()[0].url).toContain(WIN.uuid as string));
    expect(activeSockets()).toHaveLength(1);
  });

  it("falls back to the first target when the deep-linked instance is not in the range", async () => {
    mockApi.mockResolvedValue(currentRange());
    renderWorkspace("/mission-control/terminal/99999999-9999-9999-9999-999999999999/");

    await waitFor(() => expect(activeSockets()).toHaveLength(1));
    expect(activeSockets()[0].url).toContain(KALI.uuid as string);
  });

  it("tells the user to launch a range instead of connecting when none is active", async () => {
    mockApi.mockResolvedValue({ has_range: false, range: null } as CurrentRangeResponse);
    renderWorkspace();

    expect(await screen.findByText(/no active range/i)).toBeInTheDocument();
    expect(activeSockets()).toHaveLength(0);
  });

  it("does not open a terminal while the range is still provisioning", async () => {
    mockApi.mockResolvedValue(currentRange({ status: "provisioning", is_ready: false }));
    renderWorkspace();

    expect(await screen.findByText(/not ready/i)).toBeInTheDocument();
    expect(activeSockets()).toHaveLength(0);
  });

  it("reports a failed range read without opening a socket", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "server_error", message: "Server error" }));
    renderWorkspace();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(activeSockets()).toHaveLength(0);
  });

  it("explains an active range that has no console-capable devices", async () => {
    mockApi.mockResolvedValue(currentRange({ instances: [] }));
    renderWorkspace();

    expect(await screen.findByText(/no devices/i)).toBeInTheDocument();
    expect(activeSockets()).toHaveLength(0);
  });

  it("re-points a split pane when its device select changes, keeping both panes distinct", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue(currentRange({ instances: [KALI, WIN, WEB] }));
    renderWorkspace();

    await screen.findAllByRole("tab");
    await user.click(screen.getByRole("button", { name: /split/i }));
    await waitFor(() => expect(activeSockets()).toHaveLength(2));

    const leftSelect = screen.getByLabelText(/left pane device/i);
    await user.selectOptions(leftSelect, WEB.uuid as string);

    await waitFor(() => {
      const urls = activeSockets().map((socket) => socket.url);
      expect(urls.some((url) => url.includes(WEB.uuid as string))).toBe(true);
    });
    expect(activeSockets()).toHaveLength(2);
  });

  it("swaps the panes when a pane is pointed at the device the other pane shows, keeping two sockets", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue(currentRange());
    renderWorkspace();

    await screen.findAllByRole("tab");
    await user.click(screen.getByRole("button", { name: /split/i }));
    await waitFor(() => expect(activeSockets()).toHaveLength(2));

    // Left shows KALI, right shows WIN. Point left at WIN.
    await user.selectOptions(screen.getByLabelText(/left pane device/i), WIN.uuid as string);

    await waitFor(() => expect(screen.getByLabelText(/left pane device/i)).toHaveValue(WIN.uuid as string));
    expect(screen.getByLabelText(/right pane device/i)).toHaveValue(KALI.uuid as string);
    expect(activeSockets()).toHaveLength(2);
  });

  it("keeps the RDP action available per pane and routes it through the shared opener", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue(currentRange());
    renderWorkspace();

    await screen.findAllByRole("tab");
    await user.click(screen.getByRole("button", { name: /open rdp session on kali-01/i }));

    expect(openGuacamole).toHaveBeenCalledWith({ protocol: "rdp", instanceUuid: KALI.uuid });
  });

  it("names the layout controls so they are operable without color or icon cues", async () => {
    mockApi.mockResolvedValue(currentRange());
    renderWorkspace();

    const tabsButton = await screen.findByRole("button", { name: /tabs/i });
    const splitButton = screen.getByRole("button", { name: /split/i });
    expect(tabsButton).toHaveAttribute("aria-pressed", "true");
    expect(splitButton).toHaveAttribute("aria-pressed", "false");
  });

  it("has no axe violations in either layout", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue(currentRange());
    const { container } = renderWorkspace();

    await screen.findAllByRole("tab");
    expect((await axe(container)).violations).toEqual([]);

    await user.click(screen.getByRole("button", { name: /split/i }));
    await waitFor(() => expect(activeSockets()).toHaveLength(2));
    expect((await axe(container)).violations).toEqual([]);
  });

  it("tears every terminal socket down when the workspace unmounts", async () => {
    mockApi.mockResolvedValue(currentRange());
    const { unmount } = renderWorkspace();

    await waitFor(() => expect(activeSockets()).toHaveLength(1));
    unmount();
    expect(activeSockets()).toHaveLength(0);
  });
});

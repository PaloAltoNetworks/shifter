import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { CurrentRangeResponse, RangePresentation } from "@/api/types";
import { FakeWebSocket, installFakeWebSocket, latestSocket } from "@/test/fake-websocket";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiDownload: vi.fn(), apiFetch: vi.fn() }));

import { apiDownload, apiFetch } from "@/api/client";

import { RangeDashboardPage } from "./RangeDashboardPage";

const mockApi = vi.mocked(apiFetch);
const mockDownload = vi.mocked(apiDownload);

let restoreWebSocket: () => void;

function currentRange(overrides: Partial<RangePresentation> = {}): CurrentRangeResponse {
  const range: RangePresentation = {
    request_id: "11111111-1111-1111-1111-111111111111",
    range_id: 42,
    scenario_id: "basic",
    user_id: 7,
    status: "ready",
    instances: [
      {
        uuid: "22222222-2222-2222-2222-222222222222",
        name: "kali-01",
        role: "attacker",
        os_type: "kali",
        join_domain: false,
        ami_key: "kali",
        private_ip: "10.0.0.5",
      },
    ],
    agent_name: "agent-1",
    range_type: "demo",
    is_ready: true,
    is_terminal: false,
    is_active: true,
    pause_supported: true,
    resume_supported: true,
    ...overrides,
  };
  return {
    has_range: true,
    range,
    connection_urls: [],
    raes_projection: null,
    raes_participant_runtime: null,
    lifecycle: {
      expires_at: "2026-08-18T12:00:00Z",
      maximum_expires_at: "2027-07-19T12:00:00Z",
      extension_days: 30,
      can_extend: true,
    },
    vpn_profile_available: true,
  };
}

const EMPTY_RANGE: CurrentRangeResponse = {
  has_range: false,
  range: null,
  connection_urls: [],
  raes_projection: null,
  raes_participant_runtime: null,
  lifecycle: null,
  vpn_profile_available: false,
};

beforeEach(() => {
  mockApi.mockReset();
  mockDownload.mockReset();
  restoreWebSocket = installFakeWebSocket();
});

afterEach(() => {
  restoreWebSocket();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("RangeDashboardPage", () => {
  it("shows a loading skeleton before the range resolves", () => {
    mockApi.mockReturnValue(new Promise(() => {}));
    const { container } = renderRoute(<RangeDashboardPage />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("shows a friendly empty state with a launch link when there is no active range", async () => {
    mockApi.mockResolvedValue(EMPTY_RANGE);
    renderRoute(<RangeDashboardPage />);
    expect(await screen.findByText("No active range")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Launch a range" });
    expect(link).toHaveAttribute("href", "/mission-control/launch/");
  });

  it("renders an error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<RangeDashboardPage />);
    expect(await screen.findByText("Could not load your range")).toBeInTheDocument();
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("renders a populated range with status, instances, and lifecycle actions", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2026-07-19T12:00:00Z").valueOf());
    mockApi.mockResolvedValue(currentRange());
    renderRoute(<RangeDashboardPage />);

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("kali-01")).toBeInTheDocument();
    expect(screen.getByText("Attacker")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Destroy" })).toBeInTheDocument();
    expect(screen.getByText("Expires in 30 days")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extend by up to 30 days" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download VPN profile" })).toBeInTheDocument();
    // The maximum lifetime (the primary user-visible expression of the configurable
    // lease policy) is rendered from maximum_expires_at, distinct from expires_at (#27).
    const maxFormatted = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
      new Date("2027-07-19T12:00:00Z"),
    );
    expect(
      screen.getByText(
        (_content, element) =>
          element?.tagName === "P" &&
          (element.textContent ?? "").includes("Maximum lifetime:") &&
          (element.textContent ?? "").includes(maxFormatted),
      ),
    ).toBeInTheDocument();
  });

  it("hides Pause when the server reports the range is not pause/resume-safe (#614)", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2026-07-19T12:00:00Z").valueOf());
    mockApi.mockResolvedValue(currentRange({ status: "ready", pause_supported: false }));
    renderRoute(<RangeDashboardPage />);

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    // Destroy remains available; only pause/resume is capability-gated.
    expect(screen.getByRole("button", { name: "Destroy" })).toBeInTheDocument();
  });

  it("hides Resume when the server reports the range is not pause/resume-safe (#614)", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2026-07-19T12:00:00Z").valueOf());
    mockApi.mockResolvedValue(currentRange({ status: "paused", resume_supported: false }));
    renderRoute(<RangeDashboardPage />);

    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("confirms a server-bounded extension without sending a caller deadline", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/range/") return Promise.resolve(currentRange());
      if (path === "/mission-control/range/extend/") {
        return Promise.resolve({ lifecycle: currentRange().lifecycle });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    const user = userEvent.setup();
    renderRoute(<RangeDashboardPage />);

    await user.click(await screen.findByRole("button", { name: "Extend by up to 30 days" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Extend range" }));

    expect(mockApi).toHaveBeenCalledWith("/mission-control/range/extend/", { method: "POST" });
    // The confirmation dialog dismisses once the server-bounded extension succeeds.
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("downloads the VPN profile through bounded binary delivery and revokes the object URL", async () => {
    mockApi.mockResolvedValue(currentRange());
    mockDownload.mockResolvedValue(new Blob(["client\n"], { type: "application/x-openvpn-profile" }));
    const createObjectURL = vi.fn().mockReturnValue("blob:mission-control-profile");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    renderRoute(<RangeDashboardPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Download VPN profile" }));

    await waitFor(() => expect(mockDownload).toHaveBeenCalledTimes(1));
    expect(mockDownload).toHaveBeenCalledWith("/mission-control/range/vpn-profile/", {
      method: "POST",
      expectedMediaType: "application/x-openvpn-profile",
      maxBytes: 64 * 1024,
    });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mission-control-profile");
    click.mockRestore();
  });

  it("hides extension and VPN actions when the server says they are unavailable", async () => {
    const response = currentRange();
    response.lifecycle = response.lifecycle ? { ...response.lifecycle, can_extend: false } : null;
    response.vpn_profile_available = false;
    mockApi.mockResolvedValue(response);

    renderRoute(<RangeDashboardPage />);

    await screen.findByText("Ready");
    expect(screen.queryByRole("button", { name: /Extend by/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download VPN profile" })).not.toBeInTheDocument();
  });

  it("renders the server-provided extension increment with no client fallback constant (#27)", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2026-07-19T12:00:00Z").valueOf());
    const response = currentRange();
    // A deployment-configured 7-day increment must drive the button label; the SPA
    // has no hardcoded 30-day fallback.
    response.lifecycle = response.lifecycle ? { ...response.lifecycle, extension_days: 7 } : null;
    mockApi.mockResolvedValue(response);

    renderRoute(<RangeDashboardPage />);

    expect(await screen.findByRole("button", { name: "Extend by up to 7 days" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Extend by up to 30 days" })).not.toBeInTheDocument();
  });

  it("renders per-instance terminal/Guacamole actions for a console-capable instance", async () => {
    mockApi.mockResolvedValue(currentRange());
    renderRoute(<RangeDashboardPage />);

    await screen.findByText("kali-01");
    expect(screen.getByRole("link", { name: "Open terminal" })).toHaveAttribute(
      "href",
      "/mission-control/terminal/22222222-2222-2222-2222-222222222222/",
    );
    expect(screen.getByRole("button", { name: "Open SSH session" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open RDP session" })).toBeInTheDocument();
  });

  it("shows an offline live indicator before the socket connects, then live once open", async () => {
    mockApi.mockResolvedValue(currentRange());
    renderRoute(<RangeDashboardPage />);

    await screen.findByText("Ready");
    expect(screen.getByText("Offline")).toBeInTheDocument();

    act(() => latestSocket().emitOpen());
    expect(await screen.findByText("Live")).toBeInTheDocument();
  });

  it("opens the range-status socket at the range's request_id", async () => {
    mockApi.mockResolvedValue(currentRange());
    renderRoute(<RangeDashboardPage />);

    await screen.findByText("Ready");
    expect(latestSocket().url).toBe(
      `ws://${window.location.host}/ws/range-status/11111111-1111-1111-1111-111111111111/`,
    );
  });

  it("does not open a range-status socket when there is no active range", async () => {
    mockApi.mockResolvedValue(EMPTY_RANGE);
    renderRoute(<RangeDashboardPage />);

    await screen.findByText("No active range");
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("confirms and issues the destroy mutation with the range's request_id", async () => {
    mockApi.mockResolvedValue(currentRange());
    const user = userEvent.setup();
    renderRoute(<RangeDashboardPage />);

    await screen.findByText("Ready");
    await user.click(screen.getByRole("button", { name: "Destroy" }));

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Destroy" }));

    expect(mockApi).toHaveBeenCalledWith("/mission-control/range/destroy/", {
      method: "POST",
      body: { request_id: "11111111-1111-1111-1111-111111111111" },
    });
  });

  it("has no axe violations when a range is loaded", async () => {
    mockApi.mockResolvedValue(currentRange());
    const { container } = renderRoute(<RangeDashboardPage />);
    await screen.findByText("Ready");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

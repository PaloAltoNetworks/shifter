import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiDownload: vi.fn(), apiFetch: vi.fn() }));

import { apiDownload, apiFetch } from "@/api/client";

import { RangePage } from "./RangePage";

const mockApi = vi.mocked(apiFetch);
const mockDownload = vi.mocked(apiDownload);

const BOX = { uuid: "box-uuid-1", name: "dc01", private_ip: "10.1.2.56", os_type: "windows" };
const QUEUED = {
  request_id: "req-1",
  status: "PENDING",
  status_url: "/api/v1/mission-control/guacamole/bootstrap/req-1/",
  url: "",
};
const SIGNED_URL = "https://guac.example.test/session/abc?token=SECRET";

function readyStatus(overrides: Record<string, unknown> = {}) {
  return {
    participant_id: "p1",
    status: "ready",
    range_instance_id: 5,
    vpn_profile_available: false,
    target_instances: [],
    ...overrides,
  };
}

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockApi.mockReset();
  mockDownload.mockReset();
  openSpy = vi.fn();
  vi.stubGlobal("open", openSpy);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RangePage", () => {
  it("renders a ready range's target boxes with Guacamole SSH and RDP actions only", async () => {
    mockApi.mockResolvedValue(readyStatus({ target_instances: [BOX] }));
    renderRoute(<RangePage />);

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Range instance #5")).toBeInTheDocument();
    expect(screen.getByText("dc01")).toBeInTheDocument();
    expect(screen.getByText("10.1.2.56")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open dc01 terminal" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open dc01 SSH session" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open dc01 RDP session" })).toBeInTheDocument();
  });

  it.each(["ssh", "rdp"] as const)("opens a target box %s session through the Guacamole flow", async (protocol) => {
    mockApi.mockImplementation((path: string) => {
      if (path === "/ctf/range/status/") return Promise.resolve(readyStatus({ target_instances: [BOX] }));
      if (path === `/mission-control/guacamole/${protocol}-url/`) return Promise.resolve(QUEUED);
      if (path === `/mission-control/guacamole/bootstrap/${QUEUED.request_id}/`)
        return Promise.resolve({ request_id: QUEUED.request_id, status: "SUCCEEDED", url: SIGNED_URL });
      throw new Error(`unexpected path ${path}`);
    });
    renderRoute(<RangePage />);

    fireEvent.click(await screen.findByRole("button", { name: `Open dc01 ${protocol.toUpperCase()} session` }));

    await waitFor(() => expect(openSpy).toHaveBeenCalledWith(SIGNED_URL, "_blank", "noopener,noreferrer"));
    expect(mockApi).toHaveBeenCalledWith(`/mission-control/guacamole/${protocol}-url/`, {
      method: "POST",
      body: { instance_uuid: BOX.uuid },
    });
  });

  it("hides range access until the range is ready", async () => {
    mockApi.mockResolvedValue({
      participant_id: "p1",
      status: "provisioning",
      range_instance_id: null,
      vpn_profile_available: false,
      target_instances: [],
    });
    renderRoute(<RangePage />);

    expect(await screen.findByText("Provisioning")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open .* session/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open .* terminal/ })).not.toBeInTheDocument();
    expect(screen.getByText(/becomes available once your range is ready/)).toBeInTheDocument();
  });

  it("shows an empty message when a ready range has no target boxes", async () => {
    mockApi.mockResolvedValue(readyStatus({ target_instances: [] }));
    renderRoute(<RangePage />);

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByText(/No target boxes are available/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open .* session/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open .* terminal/ })).not.toBeInTheDocument();
  });

  it("shows the VPN download only when a ready range has a profile", async () => {
    mockApi.mockResolvedValue(readyStatus({ vpn_profile_available: true }));
    renderRoute(<RangePage />);

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download VPN profile" })).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(readyStatus({ target_instances: [BOX], vpn_profile_available: true }));
    const { container } = renderRoute(<RangePage />);
    await screen.findByText("Ready");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("downloads the profile without retaining it in query state", async () => {
    mockApi.mockResolvedValue(readyStatus({ vpn_profile_available: true }));
    mockDownload.mockResolvedValue(new Blob(["client\n"], { type: "application/x-openvpn-profile" }));
    const createObjectURL = vi.fn().mockReturnValue("blob:ctf-profile");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    renderRoute(<RangePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Download VPN profile" }));

    await waitFor(() => expect(mockDownload).toHaveBeenCalledTimes(1));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:ctf-profile");
    click.mockRestore();
  });

  it("surfaces a VPN download failure", async () => {
    mockApi.mockResolvedValue(readyStatus({ vpn_profile_available: true }));
    mockDownload.mockRejectedValue(new Error("download failed"));

    renderRoute(<RangePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Download VPN profile" }));

    expect(await screen.findByText("Could not download the VPN profile.")).toBeInTheDocument();
  });
});

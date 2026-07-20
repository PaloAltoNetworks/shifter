import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import type { GuacamoleBootstrapQueued, InstancePresentation } from "@/api/types";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { InstanceTable } from "./InstanceTable";

const mockApi = vi.mocked(apiFetch);

function instance(overrides: Partial<InstancePresentation> = {}): InstancePresentation {
  return {
    uuid: "22222222-2222-2222-2222-222222222222",
    name: "kali-01",
    role: "attacker",
    os_type: "kali",
    join_domain: false,
    ami_key: "kali",
    private_ip: "10.0.0.5",
    ...overrides,
  };
}

beforeEach(() => {
  mockApi.mockReset();
  vi.stubGlobal("open", vi.fn());
});

describe("InstanceTable", () => {
  it("shows the empty state when there are no instances", () => {
    renderRoute(<InstanceTable instances={[]} />);
    expect(screen.getByText("No instances provisioned yet.")).toBeInTheDocument();
  });

  it("renders identity columns for every instance", () => {
    renderRoute(<InstanceTable instances={[instance()]} />);
    expect(screen.getByText("kali-01")).toBeInTheDocument();
    expect(screen.getByText("Attacker")).toBeInTheDocument();
    expect(screen.getByText("Kali")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.5")).toBeInTheDocument();
  });

  it("renders a Terminal link plus SSH/RDP Guacamole buttons for a console-capable instance", () => {
    renderRoute(<InstanceTable instances={[instance()]} />);

    const terminalLink = screen.getByRole("link", { name: "Open terminal" });
    expect(terminalLink).toHaveAttribute("href", "/mission-control/terminal/22222222-2222-2222-2222-222222222222/");
    expect(screen.getByRole("button", { name: "Open SSH session" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open RDP session" })).toBeInTheDocument();
  });

  it("renders the same actions for a Windows instance (connect_terminal has no os_type gate)", () => {
    renderRoute(<InstanceTable instances={[instance({ role: "dc", os_type: "windows" })]} />);
    expect(screen.getByRole("link", { name: "Open terminal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open SSH session" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open RDP session" })).toBeInTheDocument();
  });

  it("does not render terminal/Guacamole actions for an NGFW-role instance", () => {
    renderRoute(<InstanceTable instances={[instance({ role: "ngfw", os_type: "panos", name: "ngfw-01" })]} />);
    expect(screen.getByText("ngfw-01")).toBeInTheDocument();
    expect(screen.getByText("Managed via NGFW")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open terminal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open (SSH|RDP) session/ })).not.toBeInTheDocument();
  });

  it("does not render actions when the instance has no uuid", () => {
    renderRoute(<InstanceTable instances={[instance({ uuid: null })]} />);
    expect(screen.queryByRole("link", { name: "Open terminal" })).not.toBeInTheDocument();
  });

  it("announces busy state on the SSH button while its bootstrap is in flight, then clears it", async () => {
    let resolvePost!: (value: GuacamoleBootstrapQueued) => void;
    mockApi.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePost = resolve;
        }),
    );
    const user = userEvent.setup();
    renderRoute(<InstanceTable instances={[instance()]} />);

    const sshButton = screen.getByRole("button", { name: "Open SSH session" });
    const rdpButton = screen.getByRole("button", { name: "Open RDP session" });
    await user.click(sshButton);

    expect(sshButton).toBeDisabled();
    expect(sshButton).toHaveAttribute("aria-busy", "true");
    // Busy state is per-button: RDP stays usable while SSH bootstraps.
    expect(rdpButton).not.toBeDisabled();

    resolvePost({
      request_id: "44444444-4444-4444-4444-444444444444",
      status: "FAILED",
      status_url: "",
      url: "",
    });
    mockApi.mockResolvedValue({
      request_id: "44444444-4444-4444-4444-444444444444",
      status: "FAILED",
      error: "No SSH key configured",
    });

    await waitFor(() => expect(sshButton).not.toBeDisabled());
    expect(await screen.findByRole("alert")).toHaveTextContent("No SSH key configured");
  });

  it("has no axe violations", async () => {
    const { container } = renderRoute(<InstanceTable instances={[instance()]} />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

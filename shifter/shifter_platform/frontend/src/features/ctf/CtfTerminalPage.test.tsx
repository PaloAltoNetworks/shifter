import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("@/features/mission-control/TerminalPage", () => ({
  TerminalPage: ({ instanceUuid }: { instanceUuid?: string }) => <div>terminal-for-{instanceUuid}</div>,
}));

import { apiFetch } from "@/api/client";

import { CtfTerminalPage } from "./CtfTerminalPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

describe("CtfTerminalPage", () => {
  it("opens the participant's visible range target without leaving the CTF route", async () => {
    mockApi.mockResolvedValue({
      participant_id: "participant-1",
      status: "ready",
      range_instance_id: 11,
      vpn_profile_available: true,
      target_instances: [{ uuid: "kali-uuid", name: "kali", private_ip: "10.50.2.35", os_type: "kali" }],
    });

    renderRoute(<CtfTerminalPage />, { path: "/ctf/terminal/", initialEntries: ["/ctf/terminal/"] });

    expect(await screen.findByText("terminal-for-kali-uuid")).toBeInTheDocument();
  });

  it("keeps the participant in the CTF workflow while a range is not ready", async () => {
    mockApi.mockResolvedValue({
      participant_id: "participant-1",
      status: "provisioning",
      range_instance_id: 11,
      vpn_profile_available: false,
      target_instances: [],
    });

    renderRoute(<CtfTerminalPage />, { path: "/ctf/terminal/", initialEntries: ["/ctf/terminal/"] });

    expect(await screen.findByText("Terminal is not ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View range" })).toHaveAttribute("href", "/ctf/range/");
  });
});

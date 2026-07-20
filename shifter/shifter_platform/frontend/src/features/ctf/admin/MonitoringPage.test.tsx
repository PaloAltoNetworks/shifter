import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { MonitoringPage } from "./MonitoringPage";

const mockApi = vi.mocked(apiFetch);

function render() {
  return renderRoute(<MonitoringPage defaultTab="scoreboard" />, {
    path: "/ctf/admin/events/:eventId/monitoring",
    initialEntries: ["/ctf/admin/events/e1/monitoring"],
  });
}

beforeEach(() => mockApi.mockReset());

describe("MonitoringPage", () => {
  it("renders the tabs and the default scoreboard content", async () => {
    mockApi.mockResolvedValue({
      team_mode: false,
      frozen: false,
      rankings: [{ participant_id: "p1", name: "Ada Lovelace", score: 300, solve_count: 3, rank: 1 }],
    });
    render();
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Scoreboard" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Ranges" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Analytics" })).toBeInTheDocument();
  });

  it("shows the scoreboard empty state", async () => {
    mockApi.mockResolvedValue({ team_mode: false, frozen: false, rankings: [] });
    render();
    expect(await screen.findByText("No scores yet")).toBeInTheDocument();
  });

  it("loads the scoreboard from the organizer-scoreboard endpoint", async () => {
    mockApi.mockImplementation((path: string) =>
      path === "/ctf/events/e1/organizer-scoreboard/"
        ? Promise.resolve({
            team_mode: false,
            frozen: false,
            rankings: [{ participant_id: "p1", name: "Ada Lovelace", score: 300, solve_count: 3, rank: 1 }],
          })
        : Promise.resolve({}),
    );
    render();
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    // The organizer monitoring board must use the full-visibility organizer read,
    // not the public `/ctf/events/<id>/scoreboard/` hook (which honors freeze/hide).
    expect(mockApi).toHaveBeenCalledWith("/ctf/events/e1/organizer-scoreboard/", expect.anything());
  });
});

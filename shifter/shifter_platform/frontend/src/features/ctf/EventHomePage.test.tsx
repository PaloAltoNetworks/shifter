import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventHomePage } from "./EventHomePage";

const mockApi = vi.mocked(apiFetch);

function currentEvent(participant: Record<string, unknown> = {}) {
  return {
    event: {
      id: "e1",
      name: "Spring CTF",
      description: "A friendly competition.",
      status: "active",
      team_mode: true,
      scoring_mode: "static",
      rating_visibility: "disabled",
      attempt_limit_mode: "unlimited",
      scoreboard_visible: true,
      event_start: null,
      event_end: null,
      registration_deadline: null,
      rules: "",
    },
    participant: {
      id: "p1",
      name: "Alice",
      status: "active",
      range_status: "",
      cached_score: 350,
      cached_solve_count: 4,
      team: { id: "t1", name: "Blue Team" },
      bracket: null,
      ...participant,
    },
  };
}

beforeEach(() => mockApi.mockReset());

function withSchedule() {
  const base = currentEvent() as { event: Record<string, unknown>; participant: Record<string, unknown> };
  const start = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  const end = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString();
  base.event = { ...base.event, event_start: start, event_end: end, rules: "Play **fair**." };
  return base;
}

describe("EventHomePage", () => {
  it("lists past announcements", async () => {
    mockApi.mockImplementation((...args: unknown[]) =>
      Promise.resolve(
        String(args[0] ?? "").includes("/me/announcements/")
          ? {
              announcements: [
                { id: "a1", subject: "Bridge is open", body: "Go **fast**.", sent_at: "2026-08-01T10:00:00Z" },
              ],
            }
          : currentEvent(),
      ),
    );
    renderRoute(<EventHomePage />);
    expect(await screen.findByText("Announcements")).toBeInTheDocument();
    expect(screen.getByText("Bridge is open")).toBeInTheDocument();
    expect(screen.getByText("fast")).toBeInTheDocument();
  });

  it("shows the countdown, schedule, and rules", async () => {
    mockApi.mockResolvedValue(withSchedule());
    renderRoute(<EventHomePage />);
    expect(await screen.findByText("Starts in")).toBeInTheDocument();
    expect(screen.getByText(/Ends /)).toBeInTheDocument();
    expect(screen.getByText("Rules")).toBeInTheDocument();
    expect(screen.getByText("fair")).toBeInTheDocument();
  });

  it("renders the event and participant state", async () => {
    mockApi.mockResolvedValue(currentEvent());
    renderRoute(<EventHomePage />);
    expect(await screen.findByRole("heading", { name: "Spring CTF" })).toBeInTheDocument();
    expect(screen.getByText("350")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Team: Blue Team")).toBeInTheDocument();
  });

  it("links to the other participant surfaces", async () => {
    mockApi.mockResolvedValue(currentEvent());
    renderRoute(<EventHomePage />);
    expect(await screen.findByRole("link", { name: "Challenges" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Scoreboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Team" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Range" })).toBeInTheDocument();
  });

  it("renders the solo state when the participant has no team", async () => {
    mockApi.mockResolvedValue(currentEvent({ team: null }));
    renderRoute(<EventHomePage />);
    expect(await screen.findByText("Solo")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(currentEvent());
    const { container } = renderRoute(<EventHomePage />);
    await screen.findByRole("heading", { name: "Spring CTF" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

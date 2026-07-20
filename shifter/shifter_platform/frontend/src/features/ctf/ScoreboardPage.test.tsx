import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ScoreboardPage } from "./ScoreboardPage";

const mockApi = vi.mocked(apiFetch);

const EVENT = { event: { id: "e1", name: "Spring CTF" }, participant: { id: "p1" } };

// Resolve both reads the page makes: the current event (for its id) and the
// event scoreboard. `path` is optional-guarded because vitest's afterEach mock
// cleanup can invoke the spy once with no arguments; that return value is
// discarded, so it safely falls through to the scoreboard payload.
function mockScoreboard(payload: Record<string, unknown>) {
  mockApi.mockImplementation(async (path?: string) => {
    if (path?.includes("/me/event/")) return EVENT;
    return payload;
  });
}

beforeEach(() => mockApi.mockReset());

describe("ScoreboardPage", () => {
  it("renders rankings", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: false,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
    });
    renderRoute(<ScoreboardPage />);
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("shows a freeze indicator when the board is frozen", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: true,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
    });
    renderRoute(<ScoreboardPage />);
    expect(await screen.findByText("Frozen")).toBeInTheDocument();
  });

  it("shows the hidden sentinel when the scoreboard is hidden", async () => {
    mockScoreboard({ scoreboard_hidden: true });
    renderRoute(<ScoreboardPage />);
    expect(await screen.findByText("Scoreboard hidden")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: false,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
    });
    const { container } = renderRoute(<ScoreboardPage />);
    await screen.findByText("Alice");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

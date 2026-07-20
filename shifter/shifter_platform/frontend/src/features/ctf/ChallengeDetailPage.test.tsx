import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ChallengeDetailPage } from "./ChallengeDetailPage";

const mockApi = vi.mocked(apiFetch);

const ROUTE = { path: "/ctf/challenges/:id", initialEntries: ["/ctf/challenges/c1"] };

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    name: "SQL Injection",
    description: "Exploit the login form.",
    category: "web",
    points: 100,
    difficulty: "easy",
    max_attempts: 0,
    attempt_limit_mode: "unlimited",
    solved: false,
    locked: false,
    attempt_count: 0,
    attempts_remaining: null,
    timeout_retry_after: null,
    hints: [],
    next_hint_id: null,
    next_hint_cost: 0,
    points_after_next_hint: 100,
    total_hint_penalty: 0,
    files: [],
    prerequisites_met: true,
    unmet_prerequisites: [],
    connection_info: null,
    show_solution: false,
    solution: null,
    rating: null,
    ...overrides,
  };
}

// GET the detail, then return a scored result for the submit POST. Both resolve.
function mockDetailThenSubmit(correct: boolean) {
  mockApi.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (options?.method === "POST" && path.includes("/submit/")) {
      return {
        correct,
        points_awarded: correct ? 100 : 0,
        attempt_number: 1,
        score: correct ? 100 : 0,
        rank: correct ? 1 : null,
        message: correct ? "Correct!" : "Incorrect flag.",
      };
    }
    return detail();
  });
}

beforeEach(() => mockApi.mockReset());

describe("ChallengeDetailPage", () => {
  it("renders the challenge detail and flag form", async () => {
    mockApi.mockResolvedValue(detail());
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByRole("heading", { name: "SQL Injection" })).toBeInTheDocument();
    expect(screen.getByText("Exploit the login form.")).toBeInTheDocument();
    expect(screen.getByLabelText("Submit flag")).toBeInTheDocument();
  });

  it("shows a success message after a correct submission", async () => {
    mockDetailThenSubmit(true);
    renderRoute(<ChallengeDetailPage />, ROUTE);
    fireEvent.change(await screen.findByLabelText("Submit flag"), { target: { value: "FLAG{x}" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Correct!")).toBeInTheDocument();
  });

  it("shows an incorrect message after a wrong submission", async () => {
    mockDetailThenSubmit(false);
    renderRoute(<ChallengeDetailPage />, ROUTE);
    fireEvent.change(await screen.findByLabelText("Submit flag"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Incorrect flag")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(detail());
    const { container } = renderRoute(<ChallengeDetailPage />, ROUTE);
    await screen.findByRole("heading", { name: "SQL Injection" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("shows a locked notice instead of the submit form for a locked challenge", async () => {
    mockApi.mockResolvedValue(detail({ locked: true }));
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByText("Locked")).toBeInTheDocument();
    expect(screen.queryByLabelText("Submit flag")).not.toBeInTheDocument();
  });

  it("shows the rating control after a solve and records a rating", async () => {
    mockApi
      .mockResolvedValueOnce(
        detail({ solved: true, rating: { average: 4.5, count: 2, own_rating: null, public: true } }),
      )
      .mockResolvedValueOnce({ value: 5, challenge_id: "c1" })
      .mockResolvedValue(
        detail({ solved: true, rating: { average: 4.7, count: 3, own_rating: 5, public: true } }),
      );
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByRole("group", { name: /Rate this challenge/ })).toBeInTheDocument();
    expect(screen.getByText(/Average 4.5 from 2 ratings/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "5" }));
    expect(await screen.findByText(/Average 4.7 from 3 ratings/)).toBeInTheDocument();
  });

  it("hides the rating control when ratings are disabled or unsolved", async () => {
    mockApi.mockResolvedValue(detail({ solved: false, rating: { average: null, count: 0, own_rating: null, public: true } }));
    renderRoute(<ChallengeDetailPage />, ROUTE);
    await screen.findByRole("heading", { name: "SQL Injection" });
    expect(screen.queryByRole("group", { name: /Rate this challenge/ })).not.toBeInTheDocument();
  });
});

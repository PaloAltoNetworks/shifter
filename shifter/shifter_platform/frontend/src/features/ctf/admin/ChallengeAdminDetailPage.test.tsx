import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ChallengeAdminDetailPage } from "./ChallengeAdminDetailPage";

const mockApi = vi.mocked(apiFetch);

const CHALLENGE = {
  id: "c1",
  name: "SQL Injection",
  description: "Find the flag",
  category: "web",
  points: 100,
  difficulty: "easy",
  flag_format: "FLAG{...}",
  hints: [{ id: "h1", text: "Look at the query", penalty: 10, order: 0 }],
  max_attempts: 3,
  order: 0,
  release_time: null,
  tags: ["sqli"],
  topics: [],
  solution: "Use a UNION-based injection.",
};

function render() {
  return renderRoute(<ChallengeAdminDetailPage />, {
    path: "/ctf/admin/challenges/:challengeId",
    initialEntries: ["/ctf/admin/challenges/c1"],
  });
}

beforeEach(() => mockApi.mockReset());

describe("ChallengeAdminDetailPage", () => {
  it("renders the challenge overview, hints, and solution", async () => {
    mockApi.mockResolvedValue(CHALLENGE);
    render();
    expect(await screen.findByRole("heading", { name: "SQL Injection" })).toBeInTheDocument();
    expect(screen.getByText("Look at the query")).toBeInTheDocument();
    expect(screen.getByText("Use a UNION-based injection.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(CHALLENGE);
    const { container } = render();
    await screen.findByRole("heading", { name: "SQL Injection" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

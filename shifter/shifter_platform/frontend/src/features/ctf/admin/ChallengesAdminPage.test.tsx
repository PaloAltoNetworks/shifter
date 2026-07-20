import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ChallengesAdminPage } from "./ChallengesAdminPage";

const mockApi = vi.mocked(apiFetch);

function challenge(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    name: "SQL Injection",
    category: "web",
    points: 100,
    difficulty: "easy",
    order: 0,
    tags: [],
    topics: [],
    ...overrides,
  };
}

function render() {
  return renderRoute(<ChallengesAdminPage />, {
    path: "/ctf/admin/events/:eventId/challenges",
    initialEntries: ["/ctf/admin/events/e1/challenges"],
  });
}

beforeEach(() => mockApi.mockReset());

describe("ChallengesAdminPage", () => {
  it("renders the challenge list", async () => {
    mockApi.mockResolvedValue({ challenges: [challenge(), challenge({ id: "c2", name: "Buffer Overflow", category: "pwn" })] });
    render();
    expect(await screen.findByRole("link", { name: "SQL Injection" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Buffer Overflow" })).toBeInTheDocument();
    expect(screen.getByText("2 challenges")).toBeInTheDocument();
  });

  it("shows the empty state when there are no challenges", async () => {
    mockApi.mockResolvedValue({ challenges: [] });
    render();
    expect(await screen.findByText("No challenges yet")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue({ challenges: [challenge()] });
    const { container } = render();
    await screen.findByRole("link", { name: "SQL Injection" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

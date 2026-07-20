import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ChallengesPage } from "./ChallengesPage";

const mockApi = vi.mocked(apiFetch);

function challenge(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    name: "SQL Injection",
    category: "web",
    points: 100,
    difficulty: "easy",
    order: 0,
    solved: false,
    ...overrides,
  };
}

beforeEach(() => mockApi.mockReset());

describe("ChallengesPage", () => {
  it("renders challenges grouped by category with solved status", async () => {
    mockApi.mockResolvedValue([
      challenge(),
      challenge({ id: "c2", name: "Buffer Overflow", category: "pwn", solved: true }),
    ]);
    renderRoute(<ChallengesPage />);
    expect(await screen.findByRole("link", { name: /SQL Injection/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Web" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pwn" })).toBeInTheDocument();
    expect(screen.getByText("Solved")).toBeInTheDocument();
  });

  it("summarizes solved-of-total in the header", async () => {
    mockApi.mockResolvedValue([challenge(), challenge({ id: "c2", name: "B", solved: true })]);
    renderRoute(<ChallengesPage />);
    expect(await screen.findByText("1 of 2 solved")).toBeInTheDocument();
  });

  it("shows the empty state when there are no challenges", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<ChallengesPage />);
    expect(await screen.findByText("No challenges available yet")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue([challenge()]);
    const { container } = renderRoute(<ChallengesPage />);
    await screen.findByRole("link", { name: /SQL Injection/ });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("filters challenges by tag and clears on second click", async () => {
    mockApi.mockResolvedValue([
      challenge({ tags: ["xdr"], topics: ["sql-injection"] }),
      challenge({ id: "c2", name: "Buffer Overflow", category: "pwn", tags: ["linux"] }),
    ]);
    renderRoute(<ChallengesPage />);
    await screen.findByRole("link", { name: /SQL Injection/ });

    fireEvent.click(screen.getByRole("button", { name: "xdr" }));
    expect(screen.getByRole("link", { name: /SQL Injection/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Buffer Overflow/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "xdr" }));
    expect(screen.getByRole("link", { name: /Buffer Overflow/ })).toBeInTheDocument();
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { AdminDashboardPage } from "./AdminDashboardPage";

const mockApi = vi.mocked(apiFetch);

function event(overrides: Record<string, unknown> = {}) {
  return {
    id: "e1",
    name: "Spring CTF",
    status: "active",
    event_start: "2026-08-01T10:00:00Z",
    event_end: "2026-08-01T18:00:00Z",
    team_mode: false,
    ...overrides,
  };
}

beforeEach(() => mockApi.mockReset());

describe("AdminDashboardPage", () => {
  it("summarizes events and lists them", async () => {
    mockApi.mockResolvedValue({
      events: [event(), event({ id: "e2", name: "Fall CTF", status: "draft", team_mode: true })],
    });
    renderRoute(<AdminDashboardPage />);
    expect(await screen.findByRole("link", { name: "Spring CTF" })).toBeInTheDocument();
    expect(screen.getByText("Total events")).toBeInTheDocument();
    // One active event (Spring is active; Fall is draft).
    expect(screen.getByText("Active / open")).toBeInTheDocument();
  });

  it("shows the empty state with a create link when there are no events", async () => {
    mockApi.mockResolvedValue({ events: [] });
    renderRoute(<AdminDashboardPage />);
    expect(await screen.findByText("No events yet")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /New event/ }).length).toBeGreaterThan(0);
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue({ events: [event()] });
    const { container } = renderRoute(<AdminDashboardPage />);
    await screen.findByRole("link", { name: "Spring CTF" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventsListPage } from "./EventsListPage";

const mockApi = vi.mocked(apiFetch);

function event(overrides: Record<string, unknown> = {}) {
  return {
    id: "e1",
    name: "Spring CTF",
    status: "registration",
    event_start: "2026-08-01T10:00:00Z",
    event_end: "2026-08-01T18:00:00Z",
    team_mode: false,
    owner: { id: "7", display_name: "Owner Org" },
    access_source: "owner",
    access_capabilities: ["awards", "notifications", "participants", "submissions"],
    ...overrides,
  };
}

beforeEach(() => mockApi.mockReset());

describe("EventsListPage", () => {
  it("renders events with status and mode", async () => {
    mockApi.mockResolvedValue({
      events: [event(), event({ id: "e2", name: "Fall CTF", status: "active", team_mode: true })],
    });
    renderRoute(<EventsListPage />);
    expect(await screen.findByRole("link", { name: "Spring CTF" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fall CTF" })).toBeInTheDocument();
    expect(screen.getByText("Registration")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("2 events")).toBeInTheDocument();
  });

  it("shows the owner and a platform-admin indicator on non-owned events", async () => {
    mockApi.mockResolvedValue({
      events: [
        event({
          id: "e3",
          name: "Other Org CTF",
          owner: { id: "42", display_name: "Other Org" },
          access_source: "platform_admin",
        }),
      ],
    });
    renderRoute(<EventsListPage />);
    expect(await screen.findByRole("link", { name: "Other Org CTF" })).toBeInTheDocument();
    expect(screen.getByText("Other Org")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });

  it("shows the empty state when there are no events", async () => {
    mockApi.mockResolvedValue({ events: [] });
    renderRoute(<EventsListPage />);
    expect(await screen.findByText("No events yet")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue({ events: [event()] });
    const { container } = renderRoute(<EventsListPage />);
    await screen.findByRole("link", { name: "Spring CTF" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

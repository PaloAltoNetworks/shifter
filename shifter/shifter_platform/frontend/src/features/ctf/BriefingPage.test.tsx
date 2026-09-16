import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { axe } from "vitest-axe";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { BriefingPage } from "./BriefingPage";

const mockApi = vi.mocked(apiFetch);

const briefing = {
  id: "b1",
  title: "Mission Briefing",
  slug: "briefing",
  body: "You are on **Kali** inside Boreas Systems. Reach the range via Range -> Open.",
  order: 0,
};

function renderBriefing() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BriefingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => mockApi.mockReset());

describe("BriefingPage", () => {
  it("renders the organizer briefing markdown when present", async () => {
    mockApi.mockResolvedValue(briefing);
    renderBriefing();
    expect(await screen.findByRole("heading", { name: "Mission Briefing" })).toBeInTheDocument();
    expect(screen.getByText("Kali")).toBeInTheDocument();
  });

  it("points to Help when the event has no briefing", async () => {
    // useCtfBriefing resolves the API's 404 to null, so "no briefing" is
    // ordinary data (a pointer to generic Help), not an error state.
    mockApi.mockResolvedValue(null);
    renderBriefing();
    expect(await screen.findByText("No briefing for this event")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Help" })).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(briefing);
    const { container } = renderBriefing();
    await screen.findByRole("heading", { name: "Mission Briefing" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

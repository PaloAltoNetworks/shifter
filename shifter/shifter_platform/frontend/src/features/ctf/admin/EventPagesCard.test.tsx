import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventPagesCard } from "./EventPagesCard";

const mockApi = vi.mocked(apiFetch);

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EventPagesCard eventId="e1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => mockApi.mockReset());

describe("EventPagesCard", () => {
  it("offers an add-briefing form with the untranslated + no-secrets warning when absent", async () => {
    mockApi.mockResolvedValue({ pages: [] });
    renderCard();
    expect(await screen.findByRole("button", { name: "Add briefing" })).toBeInTheDocument();
    expect(screen.getAllByText(/not translated/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Never include flags, passwords/i)).toBeInTheDocument();
  });

  it("shows the briefing in an editor and keeps it out of the custom pages list", async () => {
    mockApi.mockResolvedValue({
      pages: [
        { id: "b1", title: "Participant Briefing", slug: "briefing", body: "on **Kali**", order: 0 },
        { id: "p1", title: "Rules", slug: "rules", body: "be nice", order: 1 },
      ],
    });
    renderCard();
    // Published briefing is editable, not add-only or view-only.
    expect(await screen.findByRole("button", { name: "Save briefing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove briefing" })).toBeInTheDocument();
    expect(screen.getByLabelText("Briefing (markdown)")).toHaveValue("on **Kali**");
    expect(screen.queryByRole("button", { name: "Add briefing" })).not.toBeInTheDocument();
    // The custom-pages list shows the ordinary page but not the reserved briefing.
    expect(screen.getByText("/rules")).toBeInTheDocument();
    expect(screen.queryByText("/briefing")).not.toBeInTheDocument();
  });

  it("edits a published briefing through the update endpoint", async () => {
    mockApi.mockImplementation((...args: unknown[]) => {
      const url = String(args[0] ?? "");
      if (url.includes("/pages/b1/")) return Promise.resolve({ id: "b1", title: "Participant Briefing", slug: "briefing", body: "updated", order: 0 });
      return Promise.resolve({ pages: [{ id: "b1", title: "Participant Briefing", slug: "briefing", body: "old", order: 0 }] });
    });
    renderCard();
    // Wait for the editor (present only once the briefing has loaded) before
    // targeting its textarea — the absent-state add form shares the label.
    await screen.findByRole("button", { name: "Save briefing" });
    fireEvent.change(screen.getByLabelText("Briefing (markdown)"), { target: { value: "updated briefing" } });
    fireEvent.click(screen.getByRole("button", { name: "Save briefing" }));

    await waitFor(() => {
      const putCall = mockApi.mock.calls.find(
        (call) => String(call[0]).includes("/pages/b1/") && (call[1] as { method?: string })?.method === "PUT",
      );
      expect(putCall).toBeDefined();
      expect((putCall?.[1] as { body?: { body?: string } })?.body?.body).toBe("updated briefing");
    });
  });
});

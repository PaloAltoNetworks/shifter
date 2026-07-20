import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ParticipantsPage } from "./ParticipantsPage";

const mockApi = vi.mocked(apiFetch);

function participant(overrides: Record<string, unknown> = {}) {
  return {
    id: "p1",
    name: "Ada Lovelace",
    email: "ada@example.com",
    status: "registered",
    team_name: null,
    registered_at: "2026-08-01T10:00:00Z",
    total_score: 300,
    ...overrides,
  };
}

function render() {
  return renderRoute(<ParticipantsPage />, {
    path: "/ctf/admin/events/:eventId/participants",
    initialEntries: ["/ctf/admin/events/e1/participants"],
  });
}

beforeEach(() => mockApi.mockReset());

describe("ParticipantsPage", () => {
  it("renders participants with a resend action", async () => {
    mockApi.mockResolvedValue({ participants: [participant()], total: 1 });
    render();
    expect(await screen.findByRole("link", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resend" })).toBeInTheDocument();
  });

  it("opens the invite dialog", async () => {
    mockApi.mockResolvedValue({ participants: [participant()], total: 1 });
    const user = userEvent.setup();
    render();
    await screen.findByRole("link", { name: "Ada Lovelace" });
    await user.click(screen.getByRole("button", { name: /Invite/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("shows the empty state when there are no participants", async () => {
    mockApi.mockResolvedValue({ participants: [], total: 0 });
    render();
    expect(await screen.findByText("No participants yet")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue({ participants: [participant()], total: 1 });
    const { container } = render();
    await screen.findByRole("link", { name: "Ada Lovelace" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

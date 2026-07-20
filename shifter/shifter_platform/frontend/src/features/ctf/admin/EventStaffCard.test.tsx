import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventStaffCard } from "./EventStaffCard";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

describe("EventStaffCard", () => {
  it("lists assigned staff with roles", async () => {
    mockApi.mockResolvedValue({
      staff: [
        { user_id: 7, email: "mod@test.com", role: "moderator", created_at: null },
        { user_id: 8, email: "judge@test.com", role: "judge", created_at: null },
      ],
    });
    renderRoute(<EventStaffCard eventId="e1" />);
    expect(await screen.findByText("mod@test.com")).toBeInTheDocument();
    expect(screen.getByText("· judge")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(2);
  });

  it("assigns a staff member by email", async () => {
    mockApi.mockResolvedValue({ staff: [] });
    renderRoute(<EventStaffCard eventId="e1" />);
    await screen.findByText("No staff assigned.");
    await userEvent.type(screen.getByLabelText("Organizer email"), "mod@test.com");
    await userEvent.click(screen.getByRole("button", { name: "Add staff" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/staff/",
      expect.objectContaining({ method: "POST", body: { email: "mod@test.com", role: "moderator" } }),
    );
  });

  it("revokes a staff member", async () => {
    mockApi.mockResolvedValue({
      staff: [{ user_id: 7, email: "mod@test.com", role: "moderator", created_at: null }],
    });
    renderRoute(<EventStaffCard eventId="e1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    expect(mockApi).toHaveBeenCalledWith("/ctf/events/e1/staff/7/", expect.objectContaining({ method: "DELETE" }));
  });
});

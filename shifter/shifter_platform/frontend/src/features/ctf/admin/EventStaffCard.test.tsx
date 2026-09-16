import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderRoute, setupUser } from "@/test/utils";

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
    const user = setupUser();
    mockApi.mockResolvedValue({ staff: [] });
    renderRoute(<EventStaffCard eventId="e1" />);
    await screen.findByText("No staff assigned.");
    await user.type(screen.getByLabelText("Organizer email"), "mod@test.com");
    await user.click(screen.getByRole("button", { name: "Add staff" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/staff/",
      expect.objectContaining({ method: "POST", body: { email: "mod@test.com", role: "moderator" } }),
    );
  });

  it("revokes a staff member", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({
      staff: [{ user_id: 7, email: "mod@test.com", role: "moderator", created_at: null }],
    });
    renderRoute(<EventStaffCard eventId="e1" />);
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    expect(mockApi).toHaveBeenCalledWith("/ctf/events/e1/staff/7/", expect.objectContaining({ method: "DELETE" }));
  });

  it("assigns a co-organizer (#1922)", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({ staff: [] });
    renderRoute(<EventStaffCard eventId="e1" />);
    await screen.findByText("No staff assigned.");
    await user.type(screen.getByLabelText("Organizer email"), "coorg@test.com");
    await user.click(screen.getByLabelText("Role"));
    await user.click(await screen.findByRole("option", { name: "Co-organizer" }));
    await user.click(screen.getByRole("button", { name: "Add staff" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/staff/",
      expect.objectContaining({ method: "POST", body: { email: "coorg@test.com", role: "co_organizer" } }),
    );
  });

  it("offers 'Make owner' only for co-organizers and transfers ownership (#1922)", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({
      staff: [
        { user_id: 7, email: "mod@test.com", role: "moderator", created_at: null },
        { user_id: 9, email: "coorg@test.com", role: "co_organizer", created_at: null },
      ],
    });
    renderRoute(<EventStaffCard eventId="e1" />);
    await screen.findByText("coorg@test.com");
    // Exactly one "Make owner" button, for the co-organizer row.
    const makeOwner = screen.getAllByRole("button", { name: "Make owner" });
    expect(makeOwner).toHaveLength(1);
    await user.click(makeOwner[0]);
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/transfer-ownership/",
      expect.objectContaining({ method: "POST", body: { user_id: 9 } }),
    );
  });

  it("renders nothing for a non-owner (owner-only surface, #1922)", () => {
    const { container } = renderRoute(<EventStaffCard eventId="e1" canManage={false} />);
    expect(container).toBeEmptyDOMElement();
    expect(mockApi).not.toHaveBeenCalled();
  });
});

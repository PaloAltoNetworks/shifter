import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";
import type { CtfOrganizerParticipantDetail } from "@/api/types";

import { ParticipantModerationCard } from "./ParticipantModerationCard";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

const BASE = {
  id: "p1",
  name: "Ada",
  email: "ada@example.com",
  status: "active",
  status_reason: "",
  role: "player",
  hidden: false,
  affiliation: "",
  username: null,
  team_name: null,
  registered_at: null,
  login_info_sent_at: null,
  last_active_at: null,
  total_score: 0,
  solved_count: 0,
  attempt_count: 0,
  event_id: "e1",
  bracket_id: null,
  bracket_name: null,
  awards: [],
} as unknown as CtfOrganizerParticipantDetail;

describe("ParticipantModerationCard", () => {
  it("offers ban and disqualify for an active player", () => {
    renderRoute(<ParticipantModerationCard participant={BASE} />);
    expect(screen.getByRole("button", { name: "Ban" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disqualify" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make observer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide from scoreboard" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Login username")).not.toBeInTheDocument();
  });

  it("sends the recorded reason with a ban", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({ ...BASE, status: "banned", status_reason: "conduct" });
    renderRoute(<ParticipantModerationCard participant={BASE} />);
    await user.type(screen.getByLabelText("Reason (recorded)"), "conduct");
    await user.click(screen.getByRole("button", { name: "Ban" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/participants/p1/ban/",
      expect.objectContaining({ method: "POST", body: { reason: "conduct" } }),
    );
  });

  it("flips to lift-ban and requalify for moderated states", () => {
    renderRoute(
      <ParticipantModerationCard participant={{ ...BASE, status: "banned", status_reason: "conduct" }} />,
    );
    expect(screen.getByRole("button", { name: "Lift ban" })).toBeInTheDocument();
    expect(screen.getByText(/Recorded reason: conduct/)).toBeInTheDocument();

    renderRoute(<ParticipantModerationCard participant={{ ...BASE, status: "disqualified" }} />);
    expect(screen.getByRole("button", { name: "Requalify" })).toBeInTheDocument();
  });

  it("renames isolated accounts", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({ ...BASE, username: "range-new" });
    renderRoute(<ParticipantModerationCard participant={{ ...BASE, username: "range-old" }} />);
    const input = screen.getByLabelText("Login username");
    await user.clear(input);
    await user.type(input, "range-new");
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/participants/p1/username/",
      expect.objectContaining({ method: "POST", body: { username: "range-new" } }),
    );
  });
});

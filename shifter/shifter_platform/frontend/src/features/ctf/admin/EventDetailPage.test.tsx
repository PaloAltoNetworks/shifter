import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventDetailPage } from "./EventDetailPage";

const mockApi = vi.mocked(apiFetch);

const EVENT = {
  id: "e1",
  name: "Spring CTF",
  description: "A spring event",
  status: "active",
  event_start: "2026-08-01T10:00:00Z",
  event_end: "2026-08-01T18:00:00Z",
  registration_deadline: null,
  scenario_id: "basic",
  auto_cleanup: true,
  cleanup_delay_hours: 24,
  max_participants: null,
  team_mode: false,
  team_size_limit: null,
  range_config: {},
  range_spinup_minutes: 30,
  submission_cooldown_seconds: 0,
  attempt_limit_mode: "none",
  attempt_limit_cooldown_seconds: 0,
  rating_visibility: "hidden",
  scoring_mode: "static",
  scoreboard_visible: true,
  scoreboard_freeze_at: null,
};

function render() {
  return renderRoute(<EventDetailPage />, {
    path: "/ctf/admin/events/:eventId",
    initialEntries: ["/ctf/admin/events/e1"],
  });
}

beforeEach(() => mockApi.mockReset());

describe("EventDetailPage", () => {
  it("renders the overview and management links", async () => {
    mockApi.mockResolvedValue(EVENT);
    render();
    expect(await screen.findByRole("heading", { name: "Spring CTF" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Challenges" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Participants" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Monitoring" })).toBeInTheDocument();
  });

  it("keeps force-delete disabled until the event name is typed", async () => {
    mockApi.mockResolvedValue(EVENT);
    const user = userEvent.setup();
    render();
    await screen.findByRole("heading", { name: "Spring CTF" });
    await user.click(screen.getByRole("button", { name: "Force delete" }));

    // The dialog confirm button is the last "Force delete" control (the header
    // action opens the dialog; the dialog footer holds the destructive confirm).
    await screen.findByText(/This destroys all provisioned ranges/);
    const dialogConfirm = screen.getAllByRole("button", { name: "Force delete" }).at(-1)!;
    expect(dialogConfirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Type the event name/), "Spring CTF");
    expect(dialogConfirm).toBeEnabled();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(EVENT);
    const { container } = render();
    await screen.findByRole("heading", { name: "Spring CTF" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

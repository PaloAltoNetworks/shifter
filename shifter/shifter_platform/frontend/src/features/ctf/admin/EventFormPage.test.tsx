import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventFormPage } from "./EventFormPage";

const mockApi = vi.mocked(apiFetch);

const EVENT = {
  id: "e1",
  name: "Spring CTF",
  description: "A spring event",
  status: "registration",
  event_start: "2026-08-01T10:00:00Z",
  event_end: "2026-08-01T18:00:00Z",
  registration_deadline: null,
  scenario_id: "",
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

function routeApi(handlers: (path: string, options?: { method?: string }) => unknown) {
  mockApi.mockImplementation((path: string, options?: { method?: string }) => Promise.resolve(handlers(path, options)));
}

beforeEach(() => mockApi.mockReset());

describe("EventFormPage (create)", () => {
  it("submits a create request via POST /ctf/events/", async () => {
    routeApi((path) => {
      if (path === "/ctf/scenarios/") return { scenarios: [{ id: "s1", name: "Basic" }] };
      if (path === "/ctf/events/") return { id: "e9", name: "New", status: "draft" };
      return {};
    });
    const user = userEvent.setup();
    renderRoute(<EventFormPage mode="create" />, { path: "/*", initialEntries: ["/ctf/admin/events/create"] });

    await user.type(await screen.findByLabelText("Name"), "New event");
    await user.click(screen.getByRole("button", { name: "Create event" }));

    await waitFor(() =>
      expect(mockApi.mock.calls.some(([p, o]) => p === "/ctf/events/" && o?.method === "POST")).toBe(true),
    );
  });
});

describe("EventFormPage (edit)", () => {
  it("loads the existing event into the form", async () => {
    routeApi((path) => {
      if (path === "/ctf/scenarios/") return { scenarios: [] };
      if (path === "/ctf/events/e1/") return EVENT;
      return {};
    });
    renderRoute(<EventFormPage mode="edit" />, {
      path: "/ctf/admin/events/:eventId/edit",
      initialEntries: ["/ctf/admin/events/e1/edit"],
    });

    expect(await screen.findByDisplayValue("Spring CTF")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
  });
});

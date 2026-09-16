import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch, type RequestOptions } from "@/api/client";

import { ParticipantDetailPage } from "./ParticipantDetailPage";

const mockApi = vi.mocked(apiFetch);

const PARTICIPANT = {
  id: "p1",
  name: "Ada Lovelace",
  email: "ada@example.com",
  status: "active",
  team_name: null,
  registered_at: "2026-08-01T10:00:00Z",
  login_info_sent_at: "2026-07-30T10:00:00Z",
  last_active_at: null,
  total_score: 300,
  solved_count: 3,
  attempt_count: 7,
  event_id: "e1",
  awards: [],
};

function routeApi(handlers: (path: string) => unknown) {
  mockApi.mockImplementation((path: string) => Promise.resolve(handlers(path)));
}

function render() {
  return renderRoute(<ParticipantDetailPage />, {
    path: "/ctf/admin/participants/:participantId",
    initialEntries: ["/ctf/admin/participants/p1"],
  });
}

beforeAll(() => {
  // Radix `Select` needs pointer-capture/scroll APIs jsdom does not implement.
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
  window.HTMLElement.prototype.releasePointerCapture = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => mockApi.mockReset());

describe("ParticipantDetailPage", () => {
  it("renders participant detail with range lifecycle controls", async () => {
    routeApi((path) => {
      if (path === "/ctf/participants/p1/") return PARTICIPANT;
      if (path === "/ctf/events/e1/ranges/")
        return { event_id: "e1", ranges: [{ participant_id: "p1", name: "Ada", email: "ada@example.com", range_instance_id: 5, range_status: "ready" }], progress: {} };
      if (path === "/ctf/events/e1/organizer-scoreboard/") return { brackets: [], rankings: [] };
      return {};
    });
    render();
    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Provision" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Destroy" })).toBeInTheDocument();
  });

  it("initializes the bracket control from the participant's assigned bracket", async () => {
    routeApi((path) => {
      if (path === "/ctf/participants/p1/")
        return { ...PARTICIPANT, bracket_id: "b2", bracket_name: "Advanced" };
      if (path === "/ctf/events/e1/ranges/") return { event_id: "e1", ranges: [], progress: {} };
      if (path === "/ctf/events/e1/organizer-scoreboard/")
        return {
          brackets: [
            { id: "b1", name: "Beginner" },
            { id: "b2", name: "Advanced" },
          ],
          rankings: [],
        };
      return {};
    });
    render();

    const bracketSelect = await screen.findByRole("combobox", { name: "Bracket" });
    expect(bracketSelect).toHaveTextContent("Advanced");
    expect(bracketSelect).not.toHaveTextContent("No bracket");
  });

  it("shows a generated participant password once and clears it when dismissed", async () => {
    mockApi.mockImplementation((path: string, options?: RequestOptions) => {
      if (path === "/ctf/participants/p1/") return Promise.resolve(PARTICIPANT);
      if (path === "/ctf/events/e1/ranges/") return Promise.resolve({ event_id: "e1", ranges: [], progress: {} });
      if (path === "/ctf/events/e1/organizer-scoreboard/") return Promise.resolve({ brackets: [], rankings: [] });
      if (path === "/ctf/participants/p1/password/" && options?.method === "POST")
        return Promise.resolve({
          participant_id: "p1",
          event_id: "e1",
          username: "range-ada",
          password: "Generated-Participant-Password-42",
          kind: "generated",
        });
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByRole("button", { name: "Manage password" }));
    expect(screen.getByRole("dialog", { name: "Reset participant password" })).toBeInTheDocument();
    expect(screen.getByText(/does not change the event shared-password policy/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate new password" }));

    expect(await screen.findByText("Generated-Participant-Password-42")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Generated-Participant-Password-42")).not.toBeInTheDocument();
  });

  it("sets an organizer-supplied password through the same dialog", async () => {
    mockApi.mockImplementation((path: string, options?: RequestOptions) => {
      if (path === "/ctf/participants/p1/") return Promise.resolve(PARTICIPANT);
      if (path === "/ctf/events/e1/ranges/") return Promise.resolve({ event_id: "e1", ranges: [], progress: {} });
      if (path === "/ctf/events/e1/organizer-scoreboard/") return Promise.resolve({ brackets: [], rankings: [] });
      if (path === "/ctf/participants/p1/password/" && options?.method === "POST")
        return Promise.resolve({
          participant_id: "p1",
          event_id: "e1",
          username: "range-ada",
          password: "Organizer-Supplied-Password-42",
          kind: "set",
        });
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByRole("button", { name: "Manage password" }));
    await user.click(screen.getByRole("button", { name: "Set a password instead" }));
    await user.type(screen.getByLabelText("New password"), "Organizer-Supplied-Password-42");
    await user.type(screen.getByLabelText("Confirm new password"), "Organizer-Supplied-Password-42");
    await user.click(screen.getByRole("button", { name: "Set participant password" }));

    expect(await screen.findByText("Organizer-Supplied-Password-42")).toBeInTheDocument();
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/participants/p1/password/",
      expect.objectContaining({
        method: "POST",
        body: { kind: "set", password: "Organizer-Supplied-Password-42" },
      }),
    );
  });
});

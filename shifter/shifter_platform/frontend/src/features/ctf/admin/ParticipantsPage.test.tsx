import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
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
  it("lets an organizer approve a pending public registration request", async () => {
    let registrationReads = 0;
    mockApi.mockImplementation((path, options) => {
      if (path === "/ctf/events/e1/registration-requests/") {
        registrationReads += 1;
        return Promise.resolve({
          requests:
            registrationReads === 1
              ? [
                  {
                    id: "r1",
                    name: "Grace Hopper",
                    email: "grace@example.com",
                    disposition: "pending",
                    created_at: "2026-08-01T09:00:00Z",
                  },
                ]
              : [],
          total: registrationReads === 1 ? 1 : 0,
        });
      }
      if (path === "/ctf/events/e1/participants/") {
        return Promise.resolve({ participants: [], total: 0 });
      }
      if (path === "/ctf/registration-requests/r1/disposition/" && options?.method === "POST") {
        return Promise.resolve({ request_id: "r1", disposition: "approved", participant_id: "p1" });
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render();

    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    expect(screen.getByText("grace@example.com")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve Grace Hopper" }));

    expect(
      mockApi.mock.calls.some(
        ([path, options]) =>
          path === "/ctf/registration-requests/r1/disposition/" &&
          options?.method === "POST" &&
          JSON.stringify(options.body) === JSON.stringify({ action: "approve" }),
      ),
    ).toBe(true);
    await waitFor(() => expect(screen.queryByText("Grace Hopper")).not.toBeInTheDocument());
    expect(registrationReads).toBeGreaterThan(1);
  });

  it("rejects a pending public registration request without using approval", async () => {
    let registrationReads = 0;
    mockApi.mockImplementation((path, options) => {
      if (path === "/ctf/events/e1/registration-requests/") {
        registrationReads += 1;
        return Promise.resolve({
          requests:
            registrationReads === 1
              ? [
                  {
                    id: "r1",
                    name: "Grace Hopper",
                    email: "grace@example.com",
                    disposition: "pending",
                    created_at: "2026-08-01T09:00:00Z",
                  },
                ]
              : [],
          total: registrationReads === 1 ? 1 : 0,
        });
      }
      if (path === "/ctf/events/e1/participants/") return Promise.resolve({ participants: [], total: 0 });
      if (path === "/ctf/registration-requests/r1/disposition/" && options?.method === "POST") {
        return Promise.resolve({ request_id: "r1", disposition: "rejected", participant_id: null });
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByRole("button", { name: "Reject Grace Hopper" }));

    expect(
      mockApi.mock.calls.some(
        ([path, options]) =>
          path === "/ctf/registration-requests/r1/disposition/" &&
          options?.method === "POST" &&
          JSON.stringify(options.body) === JSON.stringify({ action: "reject" }),
      ),
    ).toBe(true);
    await waitFor(() => expect(screen.queryByText("Grace Hopper")).not.toBeInTheDocument());
  });

  it("shows a disposition failure and keeps the pending request visible", async () => {
    mockApi.mockImplementation((path, options) => {
      if (path === "/ctf/events/e1/registration-requests/") {
        return Promise.resolve({
          requests: [
            {
              id: "r1",
              name: "Grace Hopper",
              email: "grace@example.com",
              disposition: "pending",
              created_at: "2026-08-01T09:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/ctf/events/e1/participants/") return Promise.resolve({ participants: [], total: 0 });
      if (path === "/ctf/registration-requests/r1/disposition/" && options?.method === "POST") {
        return Promise.reject(new Error("request failed"));
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByRole("button", { name: "Reject Grace Hopper" }));

    expect(await screen.findByText("Could not review the registration request.")).toBeInTheDocument();
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();
  });

  it("opens password management for a participant", async () => {
    mockApi.mockResolvedValue({ participants: [participant()], total: 1 });
    const user = userEvent.setup();
    render();
    expect(await screen.findByRole("link", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manage password" }));
    expect(await screen.findByRole("dialog", { name: "Reset participant password" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate new password" })).toBeInTheDocument();
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

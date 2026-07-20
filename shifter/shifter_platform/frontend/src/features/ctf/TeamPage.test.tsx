import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { TeamPage } from "./TeamPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

describe("TeamPage", () => {
  it("renders the team and its members", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [
        { id: "m1", name: "Alice", is_captain: true },
        { id: "m2", name: "Bob", is_captain: false },
      ],
      is_captain: false,
      team_size_limit: 4,
      invite_code: null,
    });
    renderRoute(<TeamPage />);
    expect(await screen.findByRole("heading", { name: "Blue Team" })).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("summarizes the member count", async () => {
    mockApi.mockResolvedValue({ id: "t1", name: "Blue Team", members: [{ id: "m1", name: "Alice" }] });
    renderRoute(<TeamPage />);
    expect(await screen.findByText("1 member")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue({ id: "t1", name: "Blue Team", members: [{ id: "m1", name: "Alice" }] });
    const { container } = renderRoute(<TeamPage />);
    await screen.findByRole("heading", { name: "Blue Team" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("offers create and join forms when not on a team", async () => {
    // The hook resolves the API's 404 to null (see useCtfTeam), so "no team"
    // is ordinary data, not an error state.
    mockApi.mockResolvedValue(null);
    renderRoute(<TeamPage />);
    expect(await screen.findByLabelText("Team name")).toBeInTheDocument();
    expect(screen.getByLabelText("Invite code")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create team" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join team" })).toBeInTheDocument();
  });

  it("shows captain controls with the invite code to the captain", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [
        { id: "m1", name: "Alice", is_captain: true },
        { id: "m2", name: "Bob", is_captain: false },
      ],
      is_captain: true,
      team_size_limit: 4,
      invite_code: "join-us-123",
    });
    renderRoute(<TeamPage />);
    expect(await screen.findByText("join-us-123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make captain" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disband team" })).toBeInTheDocument();
  });

  it("hides captain controls and shows leave for members", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [
        { id: "m1", name: "Alice", is_captain: true },
        { id: "m2", name: "Bob", is_captain: false },
      ],
      is_captain: false,
      team_size_limit: null,
      invite_code: null,
    });
    renderRoute(<TeamPage />);
    expect(await screen.findByRole("button", { name: "Leave team" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Regenerate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make captain" })).not.toBeInTheDocument();
  });

});

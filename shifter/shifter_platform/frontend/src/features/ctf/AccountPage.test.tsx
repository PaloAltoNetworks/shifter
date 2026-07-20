import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { AccountPage } from "./AccountPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

const PROFILE = {
  id: "p1",
  name: "Self Player",
  affiliation: "EMEA",
  email: "self@test.com",
  username: null,
  role: "player",
  status: "active",
  event: { id: "e1", name: "Spring CTF" },
  score: 250,
  solve_count: 3,
};

describe("AccountPage", () => {
  it("renders profile form with current values", async () => {
    mockApi.mockResolvedValue(PROFILE);
    renderRoute(<AccountPage />);
    expect(await screen.findByLabelText("Display name")).toHaveValue("Self Player");
    expect(screen.getByLabelText("Affiliation")).toHaveValue("EMEA");
    expect(screen.getByText(/Spring CTF/)).toBeInTheDocument();
    // Linked platform account: no self-service username section.
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
  });

  it("shows the username form for isolated accounts", async () => {
    mockApi.mockResolvedValue({ ...PROFILE, username: "range-abc123" });
    renderRoute(<AccountPage />);
    expect(await screen.findByLabelText("Username")).toHaveValue("range-abc123");
    expect(screen.getByRole("button", { name: "Change username" })).toBeInTheDocument();
  });

  it("labels observers", async () => {
    mockApi.mockResolvedValue({ ...PROFILE, role: "observer" });
    renderRoute(<AccountPage />);
    expect(await screen.findByText(/Observer — you can watch/)).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    mockApi.mockResolvedValue({ ...PROFILE, username: "range-abc123" });
    const { container } = renderRoute(<AccountPage />);
    await screen.findByLabelText("Username");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

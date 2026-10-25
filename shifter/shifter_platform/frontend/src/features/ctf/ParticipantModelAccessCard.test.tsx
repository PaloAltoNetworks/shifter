import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/api/client";
import { renderRoute } from "@/test/utils";

import { ParticipantModelAccessCard } from "./ParticipantModelAccessCard";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const api = vi.mocked(apiFetch);

beforeEach(() => {
  api.mockReset();
});

describe("ParticipantModelAccessCard", () => {
  it("shows the range's allowed aliases and status", async () => {
    api.mockResolvedValue({ state: "active", aliases: ["coding-main", "coding-small"] });
    renderRoute(<ParticipantModelAccessCard />);
    expect(await screen.findByText("coding-main")).toBeInTheDocument();
    expect(screen.getByText("coding-small")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows an unavailable state without leaking coordinates", async () => {
    api.mockResolvedValue({ state: "unavailable", aliases: [] });
    renderRoute(<ParticipantModelAccessCard />);
    expect(await screen.findByText(/Model access is not enabled/)).toBeInTheDocument();
  });
});

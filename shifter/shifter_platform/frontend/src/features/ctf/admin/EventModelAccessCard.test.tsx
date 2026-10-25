import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/api/client";
import { renderRoute } from "@/test/utils";

import { EventModelAccessCard } from "./EventModelAccessCard";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const api = vi.mocked(apiFetch);

beforeEach(() => {
  api.mockReset();
});

describe("EventModelAccessCard", () => {
  it("shows the bounded capacity assessment summary", async () => {
    api.mockResolvedValue({
      available: true,
      outcome: "admit",
      blocking: false,
      partition: "MAIN",
      reason_codes: ["headroom_ok"],
    });
    renderRoute(<EventModelAccessCard eventId="event-1" />);
    expect(await screen.findByText("admit")).toBeInTheDocument();
    expect(screen.getByText("headroom_ok")).toBeInTheDocument();
  });

  it("reports no assessment rather than a positive decision", async () => {
    api.mockResolvedValue({ available: false, outcome: null, blocking: null, partition: null, reason_codes: [] });
    renderRoute(<EventModelAccessCard eventId="event-1" />);
    expect(await screen.findByText(/No model-access capacity assessment/)).toBeInTheDocument();
  });
});

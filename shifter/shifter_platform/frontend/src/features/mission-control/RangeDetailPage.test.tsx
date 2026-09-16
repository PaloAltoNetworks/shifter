import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { CurrentRangeResponse, RangeHistory, RangeHistoryResponse, RangePresentation } from "@/api/types";
import { FakeWebSocket, installFakeWebSocket, latestSocket } from "@/test/fake-websocket";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { RangeDetailPage } from "./RangeDetailPage";

const mockApi = vi.mocked(apiFetch);

let restoreWebSocket: () => void;

const ACTIVE_REQUEST_ID = "11111111-1111-1111-1111-111111111111";
const PAST_REQUEST_ID = "22222222-2222-2222-2222-222222222222";
const UNKNOWN_REQUEST_ID = "99999999-9999-9999-9999-999999999999";

function activeRange(overrides: Partial<RangePresentation> = {}): RangePresentation {
  return {
    request_id: ACTIVE_REQUEST_ID,
    range_id: 42,
    scenario_id: "basic",
    user_id: 7,
    status: "ready",
    instances: [],
    agent_name: "agent-1",
    range_type: "demo",
    is_ready: true,
    is_terminal: false,
    is_active: true,
    pause_supported: true,
    resume_supported: true,
    ...overrides,
  };
}

const CURRENT_RANGE: CurrentRangeResponse = {
  has_range: true,
  range: activeRange(),
  connection_urls: [],
  raes_projection: null,
  raes_participant_runtime: null,
  lifecycle: {
    expires_at: "2026-08-18T12:00:00Z",
    maximum_expires_at: "2027-07-19T12:00:00Z",
    extension_days: 30,
    can_extend: true,
  },
  vpn_profile_available: true,
};

const EMPTY_CURRENT_RANGE: CurrentRangeResponse = {
  has_range: false,
  range: null,
  connection_urls: [],
  raes_projection: null,
  raes_participant_runtime: null,
  lifecycle: null,
  vpn_profile_available: false,
};

function historyEntry(overrides: Partial<RangeHistory> = {}): RangeHistory {
  return {
    request_id: PAST_REQUEST_ID,
    range_id: 10,
    scenario_id: "legacy-scenario",
    status: "destroyed",
    range_source: "cyberscript",
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-02T00:00:00Z",
    deleted_at: "2026-06-03T00:00:00Z",
    ...overrides,
  };
}

const HISTORY: RangeHistoryResponse = { ranges: [historyEntry()] };

function mockRoutes({
  currentRange = EMPTY_CURRENT_RANGE,
  history = HISTORY,
}: { currentRange?: CurrentRangeResponse; history?: RangeHistoryResponse } = {}) {
  mockApi.mockImplementation((path: string) => {
    if (path === "/mission-control/range/") return Promise.resolve(currentRange);
    if (path === "/mission-control/ranges/") return Promise.resolve(history);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function renderDetail(requestId: string) {
  return renderRoute(<RangeDetailPage />, {
    path: "/mission-control/ranges/:requestId",
    initialEntries: [`/mission-control/ranges/${requestId}`],
  });
}

beforeEach(() => {
  mockApi.mockReset();
  restoreWebSocket = installFakeWebSocket();
});

afterEach(() => {
  restoreWebSocket();
});

describe("RangeDetailPage", () => {
  it("shows a loading skeleton before the range resolves", () => {
    mockApi.mockReturnValue(new Promise(() => {}));
    const { container } = renderDetail(ACTIVE_REQUEST_ID);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("renders an error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderDetail(ACTIVE_REQUEST_ID);
    expect(await screen.findByText("Could not load this range")).toBeInTheDocument();
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("renders the full live view when the id matches the active range", async () => {
    mockRoutes({ currentRange: CURRENT_RANGE });
    renderDetail(ACTIVE_REQUEST_ID);

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Destroy" })).toBeInTheDocument();
    expect(latestSocket().url).toBe(`ws://${window.location.host}/ws/range-status/${ACTIVE_REQUEST_ID}/`);
  });

  it("renders historical metadata with a live-access note for a past range", async () => {
    mockRoutes({ currentRange: EMPTY_CURRENT_RANGE });
    renderDetail(PAST_REQUEST_ID);

    expect(await screen.findByRole("heading", { name: "legacy-scenario" })).toBeInTheDocument();
    expect(screen.getByText("Destroyed")).toBeInTheDocument();
    expect(screen.getByText(/only available for your active range/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Destroy" })).not.toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("shows a friendly not-found state for an unknown id", async () => {
    mockRoutes();
    renderDetail(UNKNOWN_REQUEST_ID);

    expect(await screen.findByText("Range not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to ranges" })).toHaveAttribute(
      "href",
      "/mission-control/ranges/",
    );
  });

  it("has no axe violations for the active-range view", async () => {
    mockRoutes({ currentRange: CURRENT_RANGE });
    const { container } = renderDetail(ACTIVE_REQUEST_ID);
    await screen.findByText("Ready");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("has no axe violations for the historical view", async () => {
    mockRoutes({ currentRange: EMPTY_CURRENT_RANGE });
    const { container } = renderDetail(PAST_REQUEST_ID);
    await screen.findByRole("heading", { name: "legacy-scenario" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

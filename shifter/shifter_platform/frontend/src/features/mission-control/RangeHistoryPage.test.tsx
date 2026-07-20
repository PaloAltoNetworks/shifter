import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { RangeHistory, RangeHistoryResponse } from "@/api/types";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { RangeHistoryPage } from "./RangeHistoryPage";

const mockApi = vi.mocked(apiFetch);

function historyEntry(overrides: Partial<RangeHistory> = {}): RangeHistory {
  return {
    request_id: "11111111-1111-1111-1111-111111111111",
    range_id: 42,
    scenario_id: "basic",
    status: "destroyed",
    range_source: "cyberscript",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
    deleted_at: "2026-07-03T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("RangeHistoryPage", () => {
  it("shows a loading skeleton before history resolves", () => {
    mockApi.mockReturnValue(new Promise(() => {}));
    const { container } = renderRoute(<RangeHistoryPage />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("shows a friendly empty state with a launch link when there is no history", async () => {
    mockApi.mockResolvedValue({ ranges: [] } satisfies RangeHistoryResponse);
    renderRoute(<RangeHistoryPage />);
    expect(await screen.findByText("No ranges yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Launch a range" })).toHaveAttribute(
      "href",
      "/mission-control/launch/",
    );
  });

  it("renders an error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<RangeHistoryPage />);
    expect(await screen.findByText("Could not load your ranges")).toBeInTheDocument();
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("renders history rows with status and a link to the detail page", async () => {
    mockApi.mockResolvedValue({ ranges: [historyEntry()] } satisfies RangeHistoryResponse);
    renderRoute(<RangeHistoryPage />);

    expect(await screen.findByText("basic")).toBeInTheDocument();
    expect(screen.getByText("Destroyed")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "basic" });
    expect(link).toHaveAttribute("href", "/mission-control/ranges/11111111-1111-1111-1111-111111111111/");
  });

  it("renders a non-linked row when the entry has no request_id", async () => {
    mockApi.mockResolvedValue({ ranges: [historyEntry({ request_id: null })] } satisfies RangeHistoryResponse);
    renderRoute(<RangeHistoryPage />);

    expect(await screen.findByText("basic")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "basic" })).not.toBeInTheDocument();
  });

  it("has no axe violations when ranges are loaded", async () => {
    mockApi.mockResolvedValue({ ranges: [historyEntry()] } satisfies RangeHistoryResponse);
    const { container } = renderRoute(<RangeHistoryPage />);
    await screen.findByText("basic");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

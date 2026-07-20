import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => ({
    principal: { id: 1, username: "staff", display_name: "Staff", is_authenticated: true, is_staff: true, is_superuser: false },
    permissions: { can_access_risk_register: true, can_access_threat_research: false },
    feature_flags: { risk_register_spa: true },
  }),
}));

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { RiskListPage } from "./RiskListPage";

const mockApi = vi.mocked(apiFetch);

function pageOf(results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("RiskListPage", () => {
  it("renders loaded risks", async () => {
    mockApi.mockResolvedValue(
      pageOf([
        {
          id: 1,
          title: "SQL injection",
          severity: "critical",
          status: "open",
          risk_score: 9,
          comment_count: 2,
          updated_at: "2026-07-05T00:00:00Z",
          is_deleted: false,
        },
      ]),
    );
    renderRoute(<RiskListPage />);
    expect(await screen.findByText("SQL injection")).toBeInTheDocument();
    // Scope to the table so the severity-filter <option> "Critical" is excluded.
    const table = screen.getByRole("table");
    expect(within(table).getByText("Critical")).toBeInTheDocument();
  });

  it("distinguishes the empty state", async () => {
    mockApi.mockResolvedValue(pageOf([]));
    renderRoute(<RiskListPage />);
    expect(await screen.findByText("No risks yet")).toBeInTheDocument();
  });

  it("renders an error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<RiskListPage />);
    expect(await screen.findByText("Could not load risks")).toBeInTheDocument();
  });

  it("shows the create action for a staff principal", async () => {
    mockApi.mockResolvedValue(pageOf([]));
    renderRoute(<RiskListPage />);
    expect(await screen.findByRole("link", { name: "New risk" })).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(
      pageOf([
        {
          id: 1,
          title: "Weak TLS",
          severity: "low",
          status: "open",
          risk_score: null,
          comment_count: 0,
          updated_at: "2026-07-05T00:00:00Z",
          is_deleted: false,
        },
      ]),
    );
    const { container } = renderRoute(<RiskListPage />);
    await screen.findByText("Weak TLS");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

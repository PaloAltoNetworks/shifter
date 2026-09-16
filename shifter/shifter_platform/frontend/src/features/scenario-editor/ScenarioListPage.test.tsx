import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ScenarioListPage } from "./ScenarioListPage";

const mockApi = vi.mocked(apiFetch);

function entry(overrides: Record<string, unknown> = {}) {
  return {
    id: "polaris",
    name: "polaris",
    scenario_type: "raes",
    source: "raes",
    is_default: false,
    enabled: true,
    staff_only: false,
    launchable: true,
    raes: {
      source_kind: "repo",
      contract_kind: "raes",
      contract_profile: "shifter",
      package_ref: "scenario-dev/polaris",
      package_version: "1.0.0",
      package_digest: "sha256:abc",
      lock_ref: "",
      lock_digest: "",
      conformance_status: "passed",
      conformance_report_ref: "",
      provenance_summary: {},
    },
    ...overrides,
  };
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScenarioListPage", () => {
  it("renders only the RAES catalog contract", async () => {
    mockApi.mockResolvedValue([entry()]);
    renderRoute(<ScenarioListPage />);
    expect(await screen.findByRole("link", { name: "polaris" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("RAES")).toBeInTheDocument();
    expect(within(table).getByText("Yes")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New scenario" })).not.toBeInTheDocument();
  });

  it("shows the RAES registration empty state", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<ScenarioListPage />);
    expect(await screen.findByText("No scenarios yet")).toBeInTheDocument();
    expect(screen.getByText("Register a RAES pack to populate the catalog.")).toBeInTheDocument();
  });

  it("renders an error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<ScenarioListPage />);
    expect(await screen.findByText("Could not load scenarios")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue([entry()]);
    const { container } = renderRoute(<ScenarioListPage />);
    await screen.findByRole("link", { name: "polaris" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

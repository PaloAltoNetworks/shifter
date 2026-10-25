import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ScenarioListPage } from "./ScenarioListPage";

const mockApi = vi.mocked(apiFetch);

function entry(overrides: Record<string, unknown> = {}) {
  return {
    id: "example",
    name: "example",
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
      package_ref: "scenario-dev/example",
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
    expect(await screen.findByRole("link", { name: "example" })).toBeInTheDocument();
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

  it("filters by name or id and reports an empty filtered result", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue([
      entry({ id: "alpha-id", name: "First Exercise" }),
      entry({ id: "beta-id", name: "Second Exercise" }),
    ]);
    renderRoute(<ScenarioListPage />);
    await screen.findByRole("link", { name: "First Exercise" });
    const search = screen.getByRole("textbox", { name: "Search scenarios" });
    await user.type(search, " FIRST ");
    expect(screen.getByRole("link", { name: "First Exercise" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Second Exercise" })).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "beta-id");
    expect(screen.getByRole("link", { name: "Second Exercise" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "First Exercise" })).not.toBeInTheDocument();
    await user.type(search, "-absent");
    expect(screen.getByText("No scenarios match these filters")).toBeInTheDocument();
    await user.clear(search);
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("selects source and availability filters and restores all rows", async () => {
    const user = userEvent.setup();
    mockApi.mockResolvedValue([
      entry({ id: "enabled", name: "Enabled exercise" }),
      entry({ id: "disabled", name: "Disabled exercise", enabled: false }),
    ]);
    renderRoute(<ScenarioListPage />);
    await screen.findByRole("link", { name: "Enabled exercise" });
    await user.click(screen.getByRole("combobox", { name: "Filter by source" }));
    await user.click(screen.getByRole("option", { name: "Raes" }));
    expect(screen.getAllByRole("link")).toHaveLength(2);
    await user.click(screen.getByRole("combobox", { name: "Filter by availability" }));
    await user.click(screen.getByRole("option", { name: "Enabled" }));
    expect(screen.getByRole("link", { name: "Enabled exercise" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Disabled exercise" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "Filter by availability" }));
    await user.click(screen.getByRole("option", { name: "Disabled" }));
    expect(screen.getByRole("link", { name: "Disabled exercise" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Enabled exercise" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "Filter by availability" }));
    await user.click(screen.getByRole("option", { name: "All availability" }));
    await user.click(screen.getByRole("combobox", { name: "Filter by source" }));
    await user.click(screen.getByRole("option", { name: "All sources" }));
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue([entry()]);
    const { container } = renderRoute(<ScenarioListPage />);
    await screen.findByRole("link", { name: "example" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

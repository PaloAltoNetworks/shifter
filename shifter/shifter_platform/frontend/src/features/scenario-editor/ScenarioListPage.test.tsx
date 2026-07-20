import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => ({
    principal: { id: 1, username: "author", display_name: "Author", is_authenticated: true, is_staff: true, is_superuser: false },
    permissions: { can_access_risk_register: false, can_access_threat_research: true },
    feature_flags: { scenario_editor_spa: true },
  }),
}));

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ScenarioListPage } from "./ScenarioListPage";

const mockApi = vi.mocked(apiFetch);

function entry(overrides: Record<string, unknown> = {}) {
  return {
    id: "basic",
    name: "Basic Range",
    scenario_type: "demo",
    source: "builtin",
    is_default: true,
    enabled: true,
    staff_only: false,
    launchable: true,
    aces: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScenarioListPage", () => {
  it("renders catalog entries with a source badge", async () => {
    mockApi.mockResolvedValue([entry(), entry({ id: "my-lab", name: "My Lab", is_default: false, source: "custom" })]);
    renderRoute(<ScenarioListPage />);
    expect(await screen.findByText("Basic Range")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Built-in")).toBeInTheDocument();
    expect(within(table).getByText("Custom")).toBeInTheDocument();
  });

  it("shows the empty state when the catalog is empty", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<ScenarioListPage />);
    expect(await screen.findByText("No scenarios yet")).toBeInTheDocument();
  });

  it("renders an error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<ScenarioListPage />);
    expect(await screen.findByText("Could not load scenarios")).toBeInTheDocument();
  });

  it("shows the create action for an authoring principal", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<ScenarioListPage />);
    expect(await screen.findByRole("link", { name: "New scenario" })).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue([entry()]);
    const { container } = renderRoute(<ScenarioListPage />);
    await screen.findByText("Basic Range");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

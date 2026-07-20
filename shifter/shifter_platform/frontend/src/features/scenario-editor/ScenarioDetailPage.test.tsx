import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

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

import { ScenarioDetailPage } from "./ScenarioDetailPage";

const mockApi = vi.mocked(apiFetch);

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: "my-lab",
    name: "My Lab",
    description: "A custom lab.",
    scenario_type: "demo",
    source: "custom",
    is_default: false,
    enabled: true,
    staff_only: false,
    launchable: true,
    editable: true,
    deletable: true,
    exportable: true,
    ngfw: false,
    instances: [{ name: "Attacker", role: "attacker", os_type: "kali", xdr_agent: false }],
    subnets: [{ name: "core", instances: ["Attacker"], connected_to: [] }],
    aces: null,
    ...overrides,
  };
}

function renderDetail(id = "my-lab") {
  return renderRoute(<ScenarioDetailPage />, {
    path: "/scenario-editor/:scenarioId",
    initialEntries: [`/scenario-editor/${id}`],
  });
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScenarioDetailPage", () => {
  it("shows edit and delete actions for an editable custom scenario", async () => {
    mockApi.mockResolvedValue(detail());
    renderDetail();
    expect(await screen.findByRole("heading", { name: "My Lab" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.getByText("Attacker")).toBeInTheDocument();
  });

  it("hides edit/delete for a read-only built-in scenario but offers clone", async () => {
    mockApi.mockResolvedValue(
      detail({ id: "basic", name: "Basic Range", source: "builtin", is_default: true, editable: false, deletable: false }),
    );
    renderDetail("basic");
    expect(await screen.findByRole("heading", { name: "Basic Range" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clone" })).toBeInTheDocument();
  });

  it("renders the ACES provenance block for an ACES scenario", async () => {
    mockApi.mockResolvedValue(
      detail({
        id: "polaris-aces",
        name: "polaris-aces",
        source: "aces",
        scenario_type: "aces",
        editable: false,
        deletable: false,
        exportable: false,
        instances: [],
        subnets: [],
        aces: {
          source_kind: "repo",
          contract_kind: "aces",
          contract_profile: "shifter",
          package_ref: "content-packages/polaris",
          package_version: "1.0.0",
          package_digest: "sha256:abc",
          lock_ref: "",
          lock_digest: "",
          conformance_status: "passed",
          conformance_report_ref: "",
          provenance_summary: {},
        },
      }),
    );
    renderDetail("polaris-aces");
    expect(await screen.findByText("ACES package provenance")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(detail());
    const { container } = renderDetail();
    await screen.findByRole("heading", { name: "My Lab" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

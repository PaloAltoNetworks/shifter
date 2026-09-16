import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ScenarioDetailPage } from "./ScenarioDetailPage";

const mockApi = vi.mocked(apiFetch);

const detail = {
  id: "polaris",
  name: "polaris",
  scenario_type: "raes",
  source: "raes",
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
};

function mockDetail() {
  mockApi.mockImplementation(async (path) => {
    if (String(path).endsWith("/realizability/")) {
      return { scenario_id: "polaris", target_id: "gce", outcome: "realizable", gaps: [] };
    }
    return detail;
  });
}

function renderDetail() {
  return renderRoute(<ScenarioDetailPage />, {
    path: "/scenario-editor/:scenarioId",
    initialEntries: ["/scenario-editor/polaris"],
  });
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScenarioDetailPage", () => {
  it("renders the read-only RAES package identity", async () => {
    mockDetail();
    renderDetail();
    expect(await screen.findByRole("heading", { name: "polaris" })).toBeInTheDocument();
    expect(screen.getByText("scenario-dev/polaris")).toBeInTheDocument();
    expect(screen.getByText("sha256:abc")).toBeInTheDocument();
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clone" })).not.toBeInTheDocument();
  });

  it("retains availability controls for the RAES source", async () => {
    mockDetail();
    renderDetail();
    expect(await screen.findByRole("button", { name: "Disable" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make staff-only" })).toBeInTheDocument();
  });

  it("renders the realizability result", async () => {
    mockDetail();
    renderDetail();
    expect(await screen.findByText("Realizable")).toBeInTheDocument();
    expect(screen.getByText("Target: gce")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockDetail();
    const { container } = renderDetail();
    await screen.findByRole("heading", { name: "polaris" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ScenarioDetailPage } from "./ScenarioDetailPage";

const mockApi = vi.mocked(apiFetch);

const detail = {
  id: "example",
  name: "example",
  scenario_type: "raes",
  source: "raes",
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
};

function mockDetail() {
  mockApi.mockImplementation(async (path) => {
    if (String(path).endsWith("/realizability/")) {
      return { scenario_id: "example", target_id: "gce", outcome: "realizable", gaps: [] };
    }
    return detail;
  });
}

function renderDetail() {
  return renderRoute(<ScenarioDetailPage />, {
    path: "/scenario-editor/:scenarioId",
    initialEntries: ["/scenario-editor/example"],
  });
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScenarioDetailPage", () => {
  it("renders the read-only RAES package identity", async () => {
    mockDetail();
    renderDetail();
    expect(await screen.findByRole("heading", { name: "example" })).toBeInTheDocument();
    expect(screen.getByText("scenario-dev/example")).toBeInTheDocument();
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

  it.each([
    { field: "enabled", before: "Disable", after: "Enable", value: false },
    { field: "staff_only", before: "Make staff-only", after: "Make available to all", value: true },
  ])("updates $field and refreshes the availability controls", async ({ field, before, after, value }) => {
    const user = userEvent.setup();
    let current = { ...detail };
    const updates: unknown[] = [];
    mockApi.mockImplementation(async (path, init) => {
      if (String(path).endsWith("/metadata/")) {
        expect(path).toBe("/cms/scenarios/example/metadata/");
        expect(init?.method).toBe("PATCH");
        updates.push(init?.body);
        current = { ...current, ...(init?.body as object) };
      }
      if (String(path).endsWith("/realizability/")) {
        return { scenario_id: "example", target_id: "gce", outcome: "realizable", gaps: [] };
      }
      return current;
    });
    renderDetail();
    await user.click(await screen.findByRole("button", { name: before }));
    expect(await screen.findByRole("button", { name: after })).toBeEnabled();
    expect(updates).toEqual([{ [field]: value }]);
    await user.click(screen.getByRole("button", { name: after }));
    await waitFor(() => expect(screen.getByRole("button", { name: before })).toBeEnabled());
    expect(updates).toEqual([{ [field]: value }, { [field]: !value }]);
  });

  it("reports a rejected detail query", async () => {
    mockApi.mockRejectedValue(new Error("unavailable"));
    renderDetail();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load scenario");
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });

  it("reports a failed update while retaining the original availability", async () => {
    const user = userEvent.setup();
    mockDetail();
    const read = mockApi.getMockImplementation()!;
    mockApi.mockImplementation(async (path, init) => {
      if (init?.method === "PATCH") throw new Error("Update failed");
      return read(path, init);
    });
    renderDetail();
    await user.click(await screen.findByRole("button", { name: "Disable" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not update availability");
    expect(screen.getByRole("button", { name: "Disable" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Enable" })).not.toBeInTheDocument();
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
    await screen.findByRole("heading", { name: "example" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

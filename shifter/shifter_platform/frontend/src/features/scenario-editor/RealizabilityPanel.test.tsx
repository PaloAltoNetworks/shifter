/**
 * Backend realizability panel (#1581, ADR-034-R3).
 *
 * The panel must surface gaps to the author, and must never let a result the
 * server refused to vouch for read as a pass. `indeterminate` is the case that
 * matters most: rendering it like `realizable` would be exactly the loophole
 * ADR-034-R3 forbids.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { RealizabilityPanel } from "./RealizabilityPanel";

const mockApi = vi.mocked(apiFetch);

function assessment(overrides: Record<string, unknown> = {}) {
  return {
    scenario_id: "pack-1",
    target_id: "gce",
    outcome: "realizable",
    gaps: [],
    ...overrides,
  };
}

const SUPPLY_GAP = {
  code: "shifter-realizability.missing-image-mapping",
  address: "provision.node.web",
  category: "image_supply",
  message: "no enabled gce base-OS image mapping for os_family 'linux'",
};

function renderPanel(enabled = true) {
  return renderRoute(<RealizabilityPanel scenarioId="pack-1" enabled={enabled} />, {
    path: "/n-editor/:scenarioId",
    initialEntries: ["/n-editor/pack-1"],
  });
}

describe("RealizabilityPanel", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  it("reports a realizable pack with its target", async () => {
    mockApi.mockResolvedValue(assessment());

    renderPanel();

    expect(await screen.findByText("Realizable")).toBeInTheDocument();
    expect(screen.getByText("Target: gce")).toBeInTheDocument();
  });

  it("shows each gap message and its location", async () => {
    mockApi.mockResolvedValue(assessment({ outcome: "not_realizable", gaps: [SUPPLY_GAP] }));

    renderPanel();

    expect(await screen.findByText("Not realizable")).toBeInTheDocument();
    expect(screen.getByText(SUPPLY_GAP.message)).toBeInTheDocument();
    expect(screen.getByText(/provision\.node\.web/)).toBeInTheDocument();
    expect(screen.getByText(/Image supply/)).toBeInTheDocument();
  });

  it("does not present an indeterminate result as realizable", async () => {
    mockApi.mockResolvedValue(
      assessment({
        outcome: "indeterminate",
        gaps: [{ ...SUPPLY_GAP, category: "source_integrity", message: "the registered pack could not be resolved" }],
      }),
    );

    renderPanel();

    expect(await screen.findByText("Cannot be checked")).toBeInTheDocument();
    expect(screen.queryByText("Realizable")).not.toBeInTheDocument();
    expect(screen.getByText(/cannot be enabled/i)).toBeInTheDocument();
  });

  it("explains a failed load instead of implying a pass", async () => {
    mockApi.mockRejectedValue(new Error("boom"));

    renderPanel();

    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText("Realizable")).not.toBeInTheDocument();
  });

  it("renders nothing and issues no request for a non-RAES scenario", () => {
    renderPanel(false);

    expect(screen.queryByText("Backend realizability")).not.toBeInTheDocument();
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("has no axe violations when showing gaps", async () => {
    mockApi.mockResolvedValue(assessment({ outcome: "not_realizable", gaps: [SUPPLY_GAP] }));

    const { container } = renderPanel();
    await screen.findByText("Not realizable");

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
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

import { ScenarioFormPage } from "./ScenarioFormPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScenarioFormPage (create)", () => {
  it("renders the structured create form with an instances section", () => {
    renderRoute(<ScenarioFormPage mode="create" />);
    expect(screen.getByLabelText("Scenario ID")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Instances" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add instance/ })).toBeInTheDocument();
  });

  it("posts a structured create payload on submit", async () => {
    mockApi.mockResolvedValue({ scenario_id: "my-lab", name: "My Lab" });
    renderRoute(<ScenarioFormPage mode="create" />);

    fireEvent.change(screen.getByLabelText("Scenario ID"), { target: { value: "my-lab" } });
    fireEvent.change(screen.getByLabelText("Name", { selector: "#f-name" }), { target: { value: "My Lab" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "A lab." } });
    fireEvent.change(screen.getByLabelText("Name", { selector: "#i-name-0" }), { target: { value: "Attacker" } });
    fireEvent.click(screen.getByRole("button", { name: "Create scenario" }));

    // Assert the actual request body, not just URL + method: a broken
    // toPayload() (dropped fields / empty instances) must fail this test.
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        expect.stringContaining("/cms/scenario-editor/scenarios/"),
        expect.objectContaining({
          method: "POST",
          body: expect.objectContaining({
            scenario_id: "my-lab",
            name: "My Lab",
            description: "A lab.",
            instances: expect.arrayContaining([
              expect.objectContaining({ name: "Attacker", role: "victim", os_type: "from_agent" }),
            ]),
          }),
        }),
      ),
    );
  });

  it("has no axe violations", async () => {
    const { container } = renderRoute(<ScenarioFormPage mode="create" />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

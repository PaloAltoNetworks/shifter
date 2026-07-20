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

import { ScenarioYamlPage } from "./ScenarioYamlPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScenarioYamlPage (create)", () => {
  it("seeds the editor with a starter template", () => {
    renderRoute(<ScenarioYamlPage mode="create" />);
    const textarea = screen.getByLabelText("Scenario YAML") as HTMLTextAreaElement;
    expect(textarea.value).toContain("id: my-new-scenario");
  });

  it("validates the YAML through the API", async () => {
    mockApi.mockResolvedValue({ valid: true, errors: [], definition: { id: "x" } });
    renderRoute(<ScenarioYamlPage mode="create" />);
    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    // Assert the request body carries the editor's YAML, not just URL + method.
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        expect.stringContaining("/cms/scenario-editor/validate-yaml/"),
        expect.objectContaining({
          method: "POST",
          body: { yaml_content: expect.stringContaining("id: my-new-scenario") },
        }),
      ),
    );
    expect(await screen.findByText("Valid scenario")).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = renderRoute(<ScenarioYamlPage mode="create" />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

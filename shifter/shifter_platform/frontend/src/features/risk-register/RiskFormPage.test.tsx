import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

import { RiskFormPage } from "./RiskFormPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => {
  mockApi.mockReset();
});

describe("RiskFormPage (create)", () => {
  it("maps DRF field errors from the envelope onto the fields", async () => {
    mockApi.mockRejectedValue(
      new ApiError(400, {
        code: "validation_error",
        message: "Invalid",
        details: { title: ["This field is required."] },
      }),
    );
    const user = userEvent.setup();
    renderRoute(<RiskFormPage mode="create" />, { path: "/risks/create", initialEntries: ["/risks/create"] });

    await user.type(screen.getByLabelText(/Description/), "A description");
    await user.click(screen.getByRole("button", { name: "Create risk" }));

    expect(await screen.findByText("This field is required.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Title/)).toHaveAttribute("aria-invalid", "true");
  });

  it("does not fetch an existing risk in create mode", async () => {
    mockApi.mockResolvedValue({});
    renderRoute(<RiskFormPage mode="create" />, { path: "/risks/create", initialEntries: ["/risks/create"] });
    // The create form should render immediately without a GET /risks/0/.
    expect(await screen.findByRole("button", { name: "Create risk" })).toBeInTheDocument();
    expect(mockApi).not.toHaveBeenCalled();
  });
});

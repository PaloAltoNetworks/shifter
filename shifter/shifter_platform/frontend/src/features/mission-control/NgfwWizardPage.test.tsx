import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { NGFWCreateResponse } from "@/api/types";
import { renderRoute, setupUser } from "@/test/utils";

const navigateMock = vi.fn();
vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { NgfwWizardPage } from "./NgfwWizardPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => {
  mockApi.mockReset();
  navigateMock.mockReset();
});

describe("NgfwWizardPage", () => {
  it("notes the deployment-profile / SCM-credential read gap", () => {
    renderRoute(<NgfwWizardPage />);
    expect(screen.getByText(/Deployment profile \/ SCM credential pickers are pending/)).toBeInTheDocument();
    expect(screen.getByText(/#1328, #1329/)).toBeInTheDocument();
  });

  it("requires a name and valid credential ids before provisioning", async () => {
    const user = setupUser();
    renderRoute(<NgfwWizardPage />);

    await user.click(screen.getByRole("button", { name: "Provision NGFW" }));

    expect(await screen.findByText("Enter a name for this NGFW.")).toBeInTheDocument();
    expect(screen.getByText("Enter the deployment profile's credential id.")).toBeInTheDocument();
    expect(screen.getByText("Enter the SCM credential's id.")).toBeInTheDocument();
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("rejects a non-numeric credential id", async () => {
    const user = setupUser();
    renderRoute(<NgfwWizardPage />);

    await user.type(screen.getByLabelText("NGFW name"), "lab-ngfw");
    await user.type(screen.getByLabelText("Deployment profile credential id"), "abc");
    await user.type(screen.getByLabelText("SCM credential id"), "7");
    await user.click(screen.getByRole("button", { name: "Provision NGFW" }));

    expect(await screen.findByText("Enter the deployment profile's credential id.")).toBeInTheDocument();
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("provisions the NGFW with a fixed pin registration method and navigates to its detail page", async () => {
    mockApi.mockResolvedValue({ id: "ngfw-app-1", name: "lab-ngfw", status: "provisioning" } satisfies NGFWCreateResponse);
    const user = setupUser();
    renderRoute(<NgfwWizardPage />);

    await user.type(screen.getByLabelText("NGFW name"), "lab-ngfw");
    await user.type(screen.getByLabelText("Deployment profile credential id"), "4");
    await user.type(screen.getByLabelText("SCM credential id"), "7");
    await user.click(screen.getByRole("button", { name: "Provision NGFW" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/ngfw/", {
        method: "POST",
        body: {
          name: "lab-ngfw",
          deployment_profile_id: 4,
          registration_method: "pin",
          scm_credential_id: 7,
        },
      }),
    );
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/mission-control/ngfw/ngfw-app-1/"));
  });

  it("shows a server error without retrying automatically", async () => {
    mockApi.mockRejectedValue(new ApiError(400, { code: "invalid", message: "Invalid SCM credential." }));
    const user = setupUser();
    renderRoute(<NgfwWizardPage />);

    await user.type(screen.getByLabelText("NGFW name"), "lab-ngfw");
    await user.type(screen.getByLabelText("Deployment profile credential id"), "4");
    await user.type(screen.getByLabelText("SCM credential id"), "7");
    await user.click(screen.getByRole("button", { name: "Provision NGFW" }));

    expect(await screen.findByText("Invalid SCM credential.")).toBeInTheDocument();
    expect(mockApi).toHaveBeenCalledTimes(1);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("has no axe violations", async () => {
    const { container } = renderRoute(<NgfwWizardPage />);
    await screen.findByRole("button", { name: "Provision NGFW" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { CredentialCreateResponse, SuccessResponse } from "@/api/types";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { CredentialsPage } from "./CredentialsPage";

const mockApi = vi.mocked(apiFetch);

async function selectOption(user: ReturnType<typeof userEvent.setup>, triggerName: string, optionName: string) {
  await user.click(await screen.findByRole("combobox", { name: triggerName }));
  await user.click(await screen.findByRole("option", { name: optionName }));
}

beforeAll(() => {
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
  window.HTMLElement.prototype.releasePointerCapture = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  mockApi.mockReset();
});

describe("CredentialsPage", () => {
  it("notes the credentials-list read gap", () => {
    renderRoute(<CredentialsPage />);
    expect(screen.getByText("Credential list is not yet available here")).toBeInTheDocument();
    expect(screen.getByText(/#1328, #1329/)).toBeInTheDocument();
  });

  it("hides type-specific fields until a credential type is selected", async () => {
    renderRoute(<CredentialsPage />);
    expect(screen.queryByLabelText("Display name")).not.toBeInTheDocument();
  });

  it("shows SCM fields for the SCM type and requires PIN id, PIN value, and region", async () => {
    const user = userEvent.setup();
    renderRoute(<CredentialsPage />);

    await selectOption(user, "Credential type", "SCM Registration");
    await user.type(screen.getByLabelText("Display name"), "prod-scm");
    await user.click(screen.getByRole("button", { name: "Save credential" }));

    expect(await screen.findByText("Enter the PIN id.")).toBeInTheDocument();
    expect(screen.getByText("Enter the PIN value.")).toBeInTheDocument();
    expect(screen.getByText("Select a licensing region.")).toBeInTheDocument();
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("creates an SCM credential with the exact serializer fields", async () => {
    mockApi.mockResolvedValue({ id: 42, name: "prod-scm", credential_type: "scm" } satisfies CredentialCreateResponse);
    const user = userEvent.setup();
    renderRoute(<CredentialsPage />);

    await selectOption(user, "Credential type", "SCM Registration");
    await user.type(screen.getByLabelText("Display name"), "prod-scm");
    await user.type(screen.getByLabelText("Folder name"), "Shared/Firewall");
    await user.type(screen.getByLabelText("PIN id"), "pin-12345");
    await user.type(screen.getByLabelText("PIN value"), "s3cret");
    await selectOption(user, "Licensing region", "Americas");
    await user.click(screen.getByRole("button", { name: "Save credential" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/credentials/", {
        method: "POST",
        body: {
          credential_type: "scm",
          name: "prod-scm",
          expires_at: null,
          scm_folder_name: "Shared/Firewall",
          scm_pin_id: "pin-12345",
          scm_pin_value: "s3cret",
          sls_region: "americas",
        },
      }),
    );
    expect(await screen.findByText(/was created with id/)).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("creates a deployment profile credential requiring only the authcode", async () => {
    mockApi.mockResolvedValue({
      id: 9,
      name: "prod-profile",
      credential_type: "deployment_profile",
    } satisfies CredentialCreateResponse);
    const user = userEvent.setup();
    renderRoute(<CredentialsPage />);

    await selectOption(user, "Credential type", "Deployment Profile");
    await user.type(screen.getByLabelText("Display name"), "prod-profile");
    await user.type(screen.getByLabelText("VM-Series authcode"), "D1234567");
    await user.click(screen.getByRole("button", { name: "Save credential" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/credentials/", {
        method: "POST",
        body: { credential_type: "deployment_profile", name: "prod-profile", expires_at: null, authcode: "D1234567" },
      }),
    );
  });

  it("shows a server error inline without retrying automatically", async () => {
    mockApi.mockRejectedValue(new ApiError(400, { code: "invalid", message: "A credential with this name already exists" }));
    const user = userEvent.setup();
    renderRoute(<CredentialsPage />);

    await selectOption(user, "Credential type", "Deployment Profile");
    await user.type(screen.getByLabelText("Display name"), "prod-profile");
    await user.type(screen.getByLabelText("VM-Series authcode"), "D1234567");
    await user.click(screen.getByRole("button", { name: "Save credential" }));

    expect(await screen.findByText("A credential with this name already exists")).toBeInTheDocument();
    expect(mockApi).toHaveBeenCalledTimes(1);
  });

  it("deletes the just-created credential behind a confirmation dialog", async () => {
    mockApi.mockResolvedValue({
      id: 9,
      name: "prod-profile",
      credential_type: "deployment_profile",
    } satisfies CredentialCreateResponse);
    const user = userEvent.setup();
    renderRoute(<CredentialsPage />);

    await selectOption(user, "Credential type", "Deployment Profile");
    await user.type(screen.getByLabelText("Display name"), "prod-profile");
    await user.type(screen.getByLabelText("VM-Series authcode"), "D1234567");
    await user.click(screen.getByRole("button", { name: "Save credential" }));
    await screen.findByText(/was created with id/);

    mockApi.mockResolvedValue({ success: true } satisfies SuccessResponse);
    await user.click(screen.getByRole("button", { name: "Delete this credential" }));
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/credentials/9/delete/", { method: "POST" }),
    );
    await waitFor(() => expect(screen.queryByText(/was created with id/)).not.toBeInTheDocument());
  });

  it("has no axe violations", async () => {
    const { container } = renderRoute(<CredentialsPage />);
    await screen.findByRole("button", { name: "Save credential" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

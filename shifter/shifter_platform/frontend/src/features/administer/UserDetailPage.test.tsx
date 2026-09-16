import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

const bootstrap = {
  principal: { id: 99, username: "root", display_name: "Root", is_authenticated: true, is_staff: true, is_superuser: true },
  permissions: { can_view_users: true, can_change_users: true, can_delete_users: true },
};

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => bootstrap,
}));

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { adminUser as detail } from "./test-fixtures";
import { UserDetailPage } from "./UserDetailPage";

const mockApi = vi.mocked(apiFetch);

// A capable admin sees the server-derived actions for an active local account.
const ACTIVE_ACTIONS = ["deactivate", "suspend", "reset_password", "transfer_ownership"];

function renderDetail() {
  return renderRoute(<UserDetailPage />, {
    path: "/administer/users/:id",
    initialEntries: ["/administer/users/1"],
  });
}

async function confirmInDialog(name: string) {
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name }));
}

beforeEach(() => {
  mockApi.mockReset();
  mockApi.mockResolvedValue(detail({ available_actions: ACTIVE_ACTIONS }));
});

describe("UserDetailPage", () => {
  it("renders the server-derived lifecycle actions for a capable admin", async () => {
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Alice Example" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suspend" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset password" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transfer ownership" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("hides lifecycle actions the server does not advertise", async () => {
    mockApi.mockReset();
    mockApi.mockResolvedValue(detail({ available_actions: [] }));
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    expect(screen.queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend" })).not.toBeInTheDocument();
    // Delete stays gated on the delete permission, not available_actions.
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("deactivates through the confirm dialog and calls the lifecycle endpoint", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await confirmInDialog("Deactivate");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/lifecycle/",
        expect.objectContaining({ method: "POST", body: { action: "deactivate" } }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("suspends through the confirm dialog and calls the lifecycle endpoint", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Suspend" }));
    await confirmInDialog("Suspend");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/lifecycle/",
        expect.objectContaining({ method: "POST", body: { action: "suspend" } }),
      ),
    );
  });

  it("shows Reinstate for a suspended account and activates it", async () => {
    mockApi.mockReset();
    mockApi.mockResolvedValue(
      detail({ is_active: false, lifecycle_state: "suspended", available_actions: ["activate", "deactivate"] }),
    );
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Reinstate" }));
    await confirmInDialog("Reinstate");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/lifecycle/",
        expect.objectContaining({ method: "POST", body: { action: "activate" } }),
      ),
    );
  });

  it("sends a password reset through the confirm dialog", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Reset password" }));
    await confirmInDialog("Send reset email");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/reset-password/",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("transfers ownership through the transfer dialog", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Transfer ownership" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Replacement user ID"), "42");
    await userEvent.click(within(dialog).getByRole("button", { name: "Transfer" }));
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/transfer-ownership/",
        expect.objectContaining({
          method: "POST",
          body: { replacement_user_id: 42, resource_kinds: ["ranges", "workspaces"] },
        }),
      ),
    );
  });

  it("soft-deletes a user through the confirm dialog and calls delete", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await confirmInDialog("Delete");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/delete/",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("grants local organizer through the confirm dialog and calls grant-organizer", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Grant CTF Organizer" }));
    await confirmInDialog("Grant");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/grant-organizer/",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("surfaces the API error inside the confirm dialog on failure", async () => {
    mockApi.mockResolvedValueOnce(detail({ available_actions: ACTIVE_ACTIONS })); // initial detail load
    mockApi.mockRejectedValueOnce(
      new ApiError(400, { code: "self_delete_forbidden", message: "You cannot delete your own account." }),
    );
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await confirmInDialog("Delete");
    expect(await screen.findByText("You cannot delete your own account.")).toBeInTheDocument();
  });

  it("renders a not-found state on 404", async () => {
    mockApi.mockReset();
    mockApi.mockRejectedValue(new ApiError(404, { code: "not_found", message: "no" }));
    renderDetail();
    expect(await screen.findByText("User not found")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockReset();
    mockApi.mockResolvedValue(
      detail({
        is_ctf_organizer: true,
        organizer_grant_source: "local",
        groups: ["CTF Organizer"],
        available_actions: ACTIVE_ACTIONS,
      }),
    );
    const { container } = renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

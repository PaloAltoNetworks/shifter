import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

const bootstrap = {
  principal: { id: 99, username: "root", display_name: "Root", is_authenticated: true, is_staff: true, is_superuser: true },
  permissions: { can_view_users: true, can_change_users: true, can_delete_users: true },
  feature_flags: { administer_spa: true },
};

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => bootstrap,
}));

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { adminUser as detail } from "./test-fixtures";
import { UserDetailPage } from "./UserDetailPage";

const mockApi = vi.mocked(apiFetch);

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
  mockApi.mockResolvedValue(detail());
});

describe("UserDetailPage", () => {
  it("renders read-only detail with lifecycle actions for a capable admin", async () => {
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Alice Example" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grant CTF Organizer" })).toBeInTheDocument();
  });

  it("deactivates a user through the confirm dialog and calls set-active", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    await userEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await confirmInDialog("Deactivate");
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/administer/users/1/set-active/",
        expect.objectContaining({ method: "POST", body: { is_active: false } }),
      ),
    );
    // The dialog closes on success.
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
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
    mockApi.mockResolvedValueOnce(detail()); // initial detail load
    mockApi.mockRejectedValueOnce(new ApiError(400, { code: "self_delete_forbidden", message: "You cannot delete your own account." }));
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
    mockApi.mockResolvedValue(detail({ is_ctf_organizer: true, organizer_grant_source: "local", groups: ["CTF Organizer"] }));
    const { container } = renderDetail();
    await screen.findByRole("heading", { name: "Alice Example" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

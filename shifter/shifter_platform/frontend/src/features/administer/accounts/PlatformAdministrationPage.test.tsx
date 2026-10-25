import { screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { apiFetch } from "@/api/client";
import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { PlatformAdministrationPage } from "./PlatformAdministrationPage";

it("offers valid identity operations without a staff or superuser presentation veto", async () => {
  const mocked = vi.mocked(apiFetch);
  mocked.mockImplementation((path, options) => {
    if (path === "/administer/users/") return Promise.resolve({ count: 1, results: [{ id: 42, display_name: "Target", email: "target@example.test" }] });
    if (path === "/administer/users/42/") return Promise.resolve({ id: 42, principal_uuid: "principal-one", display_name: "Target", email: "target@example.test", lifecycle_state: "active", available_actions: ["deactivate", "transfer_ownership"] });
    if (options?.method === "POST") return Promise.resolve({});
    return Promise.resolve({ count: 0, results: [] });
  });
  const user = setupUser();
  renderRoute(<PlatformAdministrationPage />);
  await user.click(await screen.findByRole("button", { name: "Target" }));
  await user.click(await screen.findByRole("button", { name: "Deactivate" }));
  await user.click(screen.getByRole("button", { name: "Confirm identity change" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledWith("/administer/users/42/lifecycle/", expect.objectContaining({ method: "POST", body: { action: "deactivate" } })));
});

it("edits profile metadata, confirms credential revocation and displays blocked offboarding outcomes", async () => {
  const mocked = vi.mocked(apiFetch);
  mocked.mockReset();
  mocked.mockImplementation((path, options) => {
    if (path === "/administer/users/") return Promise.resolve({ count: 1, results: [{ id: 42, display_name: "Target" }] });
    if (path === "/administer/users/42/") return Promise.resolve({ id: 42, principal_uuid: "principal-one", display_name: "Target", username: "target", email: "target@example.test", first_name: "", last_name: "", available_actions: ["transfer_ownership"] });
    if (path.endsWith("/personal-credentials/")) return Promise.resolve({ count: 1, next_offset: null, results: [{ credential_uuid: "credential", name: "Synthetic token" }] });
    if (path.endsWith("/transfer-ownership/")) return Promise.resolve({ ranges_reassigned: 1, ranges_blocked: 2, workspaces_transferred: 1, workspaces_blocked_no_membership: 0, workspaces_blocked: 0 });
    return Promise.resolve(options?.method ? {} : { count: 0, results: [] });
  });
  const user = setupUser(); renderRoute(<PlatformAdministrationPage />);
  await user.click(await screen.findByRole("button", { name: "Target" }));
  await user.type(await screen.findByLabelText("First name"), "Synthetic");
  expect(screen.getByLabelText("User email")).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Save user profile" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledWith("/administer/users/42/", expect.objectContaining({ method: "PATCH", body: { first_name: "Synthetic" } })));
  await user.click(screen.getByRole("button", { name: "Revoke Synthetic token" }));
  await user.click(screen.getByRole("button", { name: "Confirm credential revocation" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledWith("/administer/credentials/personal/credential/revoke/", expect.objectContaining({ method: "POST", body: {} })));
  await user.type(screen.getByLabelText("Replacement user ID"), "43");
  await user.click(screen.getByRole("button", { name: "Review ownership transfer" }));
  await user.click(screen.getByRole("button", { name: "Confirm offboarding transfer" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledWith("/administer/users/42/transfer-ownership/", expect.objectContaining({ body: { replacement_user_id: 43, resource_kinds: ["ranges", "workspaces"] } })));
});

it("reconciles a successful unresolved organizer command in its original scope", async () => {
  const mocked = vi.mocked(apiFetch); mocked.mockReset();
  mocked.mockImplementation((path, options) => {
    if (path === "/administer/users/") return Promise.resolve({ count: 1, results: [{ id: 42, display_name: "Target" }] });
    if (path === "/administer/users/42/") return Promise.resolve({ id: 42, principal_uuid: "principal-one", display_name: "Target", available_actions: [] });
    if (path.endsWith("/grant-organizer/")) return Promise.resolve({ operation_id: "operation", state: "unresolved" });
    if (path === "/accounts/original/authorization/operations/operation/") return Promise.resolve({ uuid: "operation", state: options?.method ? "confirmed" : "unresolved" });
    return Promise.resolve({ count: 0, results: [] });
  });
  const user = setupUser(); renderRoute(<PlatformAdministrationPage />);
  await user.click(await screen.findByRole("button", { name: "Target" }));
  await user.type(await screen.findByLabelText("Scope UUID"), "original");
  await user.click(screen.getByRole("button", { name: "Assign event creation" }));
  await user.click(await screen.findByRole("button", { name: "Reconcile status" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledWith("/accounts/original/authorization/operations/operation/", expect.objectContaining({ method: "POST" })));
});

it("allows the owning human to edit recovery email through their own session", async () => {
  const mocked = vi.mocked(apiFetch); mocked.mockReset();
  mocked.mockImplementation((path, options) => {
    if (path === "/accounts/context/") return Promise.resolve({ principal_kind: "human", principal_uuid: "principal-one" });
    if (path === "/administer/users/") return Promise.resolve({ count: 1, results: [{ id: 42, display_name: "Owner" }] });
    if (path === "/administer/users/42/") return Promise.resolve({ id: 42, principal_uuid: "principal-one", display_name: "Owner", email: "before@example.test", available_actions: [] });
    return Promise.resolve(options?.method ? {} : { count: 0, results: [] });
  });
  const user = setupUser(); renderRoute(<PlatformAdministrationPage />);
  await user.click(await screen.findByRole("button", { name: "Owner" }));
  const email = await screen.findByLabelText("User email");
  await waitFor(() => expect(email).toBeEnabled());
  await user.clear(email); await user.type(email, "owner@example.test");
  await user.click(screen.getByRole("button", { name: "Save user profile" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledWith("/administer/users/42/", expect.objectContaining({ method: "PATCH", body: { email: "owner@example.test" } })));
});

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import { renderRoute, setupUser } from "@/test/utils";
vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "@/api/client";
import { WorkspaceAdministrationPanel } from "./WorkspaceAdministrationPanel";
const mock = vi.mocked(apiFetch);
const row = { uuid: "workspace", name: "Selected workspace", is_default: false, archived_at: null, egress_policy: "status-quo", owner_principal_uuids: ["owner-one", "owner-two"] };
beforeEach(() => {
  mock.mockReset();
  mock.mockImplementation((path, options) => {
    if (path === "/accounts/account/organizations/organization/workspaces/workspace/") return Promise.resolve(row);
    if (options?.method) return Promise.resolve({ ...row, changed: true });
    if (path.endsWith("/quota/")) return Promise.resolve({ resources: [{ resource: "member_seats", usage: 2, limit: 10, mode: "enforcing" }] });
    return Promise.resolve({ count: 0, next: null, results: [] });
  });
});
const page = () => renderRoute(<WorkspaceAdministrationPanel accountUuid="account" organizationUuid="organization" workspaceUuid="workspace" />);

it("renames the selected workspace and requires lifecycle confirmation", async () => {
  const user = setupUser(); page();
  await user.clear(await screen.findByLabelText("Workspace name"));
  await user.type(screen.getByLabelText("Workspace name"), "Renamed");
  await user.click(screen.getByRole("button", { name: "Rename workspace" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/rename/", expect.objectContaining({ body: { name: "Renamed" } })));
  await user.click(screen.getByRole("button", { name: "Archive workspace" }));
  expect(mock.mock.calls.some(([path]) => path.endsWith("/archive/"))).toBe(false);
  await user.click(screen.getByRole("button", { name: "Confirm workspace change" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/archive/", expect.objectContaining({ method: "POST", body: {} })));
});

it("edits quota and egress using their canonical commands", async () => {
  const user = setupUser(); page();
  await screen.findByRole("heading", { name: "Selected workspace" });
  await user.click(screen.getByRole("tab", { name: "Quota and egress" }));
  expect(await screen.findByText(/member seats: 2/)).toBeInTheDocument();
  await user.clear(screen.getByLabelText("Quota limit")); await user.type(screen.getByLabelText("Quota limit"), "20");
  await user.selectOptions(screen.getByLabelText("Quota enforcement"), "advisory");
  await user.click(screen.getByRole("button", { name: "Save quota" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/quota-policy/", expect.objectContaining({ method: "PUT", body: { resource: "member_seats", mode: "advisory", limit: 20 } })));
  await user.selectOptions(screen.getByLabelText("Workspace egress"), "none");
  await user.click(screen.getByRole("button", { name: "Save egress" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/egress-policy/", expect.objectContaining({ method: "PUT", body: { egress_policy: "none" } })));
});

it("preserves explicit source ownership and confirms removal and transfer", async () => {
  const user = setupUser(); page();
  await screen.findByRole("heading", { name: "Selected workspace" });
  await user.click(screen.getByRole("tab", { name: "Ownership" }));
  await user.selectOptions(screen.getByLabelText("Source owner"), "owner-two");
  await user.type(screen.getByLabelText("Destination principal UUID"), "destination");
  await user.click(screen.getByRole("button", { name: "Add owner" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/owners/", expect.objectContaining({ body: { principal_uuid: "destination" } })));
  await user.click(screen.getByRole("button", { name: "Transfer ownership" }));
  await user.click(screen.getByRole("button", { name: "Confirm ownership transfer" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/transfer/", expect.objectContaining({ body: { source_principal_uuid: "owner-two", destination_principal_uuid: "destination" } })));
  await user.click(screen.getByRole("button", { name: "Remove owner owner-one" }));
  await user.click(screen.getByRole("button", { name: "Confirm owner removal" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/owners/owner-one/", expect.objectContaining({ method: "DELETE" })));
});

it("hides workspace details when policy is revoked", async () => {
  mock.mockRejectedValue(new ApiError(403, { code: "denied", message: "Workspace denied" })); page();
  expect(await screen.findByRole("alert")).toHaveTextContent("Workspace denied");
  expect(screen.queryByLabelText("Workspace name")).not.toBeInTheDocument();
});

it("preserves an existing quota limit when only the enforcement mode changes", async () => {
  const user = setupUser(); page();
  await screen.findByRole("heading", { name: "Selected workspace" });
  await user.click(screen.getByRole("tab", { name: "Quota and egress" }));
  await screen.findByText(/member seats: 2/);
  await user.selectOptions(screen.getByLabelText("Quota enforcement"), "advisory");
  await user.click(screen.getByRole("button", { name: "Save quota" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/workspace/quota-policy/", expect.objectContaining({ body: { resource: "member_seats", mode: "advisory", limit: 10 } })));
});

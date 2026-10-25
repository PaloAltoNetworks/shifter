import { screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderRoute, setupUser } from "@/test/utils";
import { ApiError } from "@/api/errors";
vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "@/api/client";
import { ScopeMembershipPanel } from "./ScopeMembershipPanel";
import { ScopeInvitationPanel } from "./ScopeInvitationPanel";
const mock = vi.mocked(apiFetch);
beforeEach(() => { mock.mockReset(); });

it("adds and confirms removing a principal fact without a role or grant", async () => {
  const principal = "11111111-1111-1111-1111-111111111111";
  mock.mockImplementation((_path, options) => Promise.resolve(options?.method ? undefined : { count: 1, results: [{ principal_uuid: principal }] }));
  const user = setupUser();
  renderRoute(<ScopeMembershipPanel scope={{ kind: "workspace", uuid: "selected" }} />);
  await user.type(await screen.findByLabelText("Member principal UUID"), principal);
  await user.click(screen.getByRole("button", { name: "Add member" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/selected/memberships/", expect.objectContaining({ body: { principal_uuid: principal } })));
  await user.click(screen.getByRole("button", { name: principal }));
  await user.click(screen.getByRole("button", { name: "Confirm removal" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith(`/workspaces/selected/memberships/${principal}/`, expect.objectContaining({ method: "DELETE" })));
});

it("issues, resends and confirms revoking invitations through the selected workspace", async () => {
  mock.mockImplementation((_path, options) => Promise.resolve(options?.method ? undefined : { count: 1, results: [{ invitation_uuid: "invitation", email: "recipient@example.test", status: "pending" }] }));
  const user = setupUser();
  renderRoute(<ScopeInvitationPanel workspaceUuid="selected" />);
  await user.type(await screen.findByLabelText("Recipient email"), "new@example.test");
  await user.click(screen.getByRole("button", { name: "Send invitation" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/selected/invitations/", expect.objectContaining({ body: { email: "new@example.test" } })));
  await user.click(screen.getByRole("button", { name: "Resend invitation" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/selected/invitations/invitation/resend/", expect.objectContaining({ method: "POST" })));
  await user.click(screen.getByRole("button", { name: "Revoke invitation" }));
  await user.click(screen.getByRole("button", { name: "Confirm revocation" }));
  await waitFor(() => expect(mock).toHaveBeenCalledWith("/workspaces/selected/invitations/invitation/revoke/", expect.objectContaining({ method: "POST" })));
});

it("does not expose invitation authoring when the scope read is denied", async () => {
  mock.mockImplementation(path => path?.includes("/denied/") ? Promise.reject(new ApiError(403, { code: "denied", message: "Scope denied" })) : Promise.resolve({ count: 0, results: [] }));
  renderRoute(<ScopeInvitationPanel workspaceUuid="denied" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Scope denied");
  expect(screen.queryByLabelText("Recipient email")).not.toBeInTheDocument();
});

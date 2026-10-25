import { screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { apiFetch } from "@/api/client";
import { renderRoute, setupUser } from "@/test/utils";
import { ScopeAuthorizationContent } from "../organization/WorkspaceAuthorizationPage";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

it("uses the selected account's journal paths and preserves idempotency recovery", async () => {
  const mocked = vi.mocked(apiFetch);
  mocked.mockImplementation((path, options) => {
    if (options?.method === "POST") return Promise.resolve({ uuid: "group-one", name: "Operators", is_active: true });
    return Promise.resolve(path.endsWith("/catalog/") ? [] : []);
  });
  const user = setupUser();
  renderRoute(<ScopeAuthorizationContent workspaceUuid={{ kind: "account", uuid: "account-one" }} />);
  await screen.findByRole("heading", { name: "Policies and groups" });
  await user.type(screen.getByLabelText("Name", { selector: "#Group-name" }), "Operators");
  await user.click(screen.getByRole("button", { name: "Create group" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledWith("/accounts/account-one/authorization/groups/", expect.objectContaining({ method: "POST", body: { name: "Operators", description: "" } })));
  expect(mocked.mock.calls.some(([path]) => path.startsWith("/workspaces/account-one"))).toBe(false);
});

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/api/errors";
import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "@/api/client";

import { AccountAdministrationPage } from "./AccountAdministrationPage";

const mockApi = vi.mocked(apiFetch);
const account = { uuid: "11111111-1111-1111-1111-111111111111", kind: "individual", name: "Personal" };

beforeEach(() => {
  mockApi.mockReset();
  mockApi.mockImplementation((path, options) => {
    if (path === "/accounts/current/") return Promise.resolve(account);
    if (path === `/accounts/${account.uuid}/` && options?.method === "PATCH") return Promise.resolve({ ...account, name: "Renamed" });
    if (path.endsWith("/memberships/")) return Promise.resolve({ count: 0, results: [] });
    return Promise.resolve({ count: 0, results: [] });
  });
});

it("loads an individual account without any account or subdivision selector", async () => {
  renderRoute(<AccountAdministrationPage individual />);
  expect(await screen.findByRole("heading", { name: "Personal" })).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: /organization|workspace|account/i })).not.toBeInTheDocument();
  expect(mockApi.mock.calls.some(([path]) => path.includes("/organizations/"))).toBe(false);
  expect(mockApi.mock.calls.some(([path]) => path === "/accounts/")).toBe(false);
});

it("submits only the account name to the exact selected account", async () => {
  const user = setupUser();
  renderRoute(<AccountAdministrationPage individual />);
  const name = await screen.findByLabelText("Account name");
  await user.clear(name);
  await user.type(name, "Renamed");
  await user.click(screen.getByRole("button", { name: "Save account" }));
  await waitFor(() => expect(mockApi).toHaveBeenCalledWith(`/accounts/${account.uuid}/`, expect.objectContaining({ method: "PATCH", body: { name: "Renamed" } })));
});

it("keeps denied account data out of the page", async () => {
  mockApi.mockRejectedValue(new ApiError(403, { code: "account_access_denied", message: "Account access denied" }));
  renderRoute(<AccountAdministrationPage individual />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Account access denied");
  expect(screen.queryByLabelText("Account name")).not.toBeInTheDocument();
});

it("pages business accounts using the authorized server count", async () => {
  mockApi.mockImplementation((path, options) => {
    if (path === "/accounts/") return Promise.resolve({ count: 51, results: options?.query?.offset ? [] : [{ ...account, kind: "team", name: "Team" }] });
    return Promise.resolve({ count: 0, results: [] });
  });
  const user = setupUser();
  renderRoute(<AccountAdministrationPage />);
  expect(await screen.findByRole("button", { name: "Team" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next accounts" }));
  await waitFor(() => expect(mockApi).toHaveBeenCalledWith("/accounts/", expect.objectContaining({ query: expect.objectContaining({ offset: 50 }) })));
});

it("selects the individual presentation from the admitted principal context", async () => {
  mockApi.mockImplementation((path) => {
    if (path === "/accounts/context/") return Promise.resolve({ principal_kind: "human", individual_account: account, accounts: { count: 1, results: [account] }, installation_actions: [] });
    if (path === "/accounts/current/") return Promise.resolve(account);
    return Promise.resolve({ count: 0, results: [] });
  });
  const { AccountAdministrationEntry } = await import("./AccountAdministrationPage");
  renderRoute(<AccountAdministrationEntry />);
  expect(await screen.findByRole("heading", { name: "Personal" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Search accounts")).not.toBeInTheDocument();
});

it("binds subdivision editing to the selected business account with a narrow PATCH", async () => {
  const team = { ...account, kind: "team", name: "Team" };
  const org = { uuid: "org-one", name: "Division", is_default: true };
  mockApi.mockImplementation(path => {
    if (path === "/accounts/") return Promise.resolve({ count: 1, results: [team] });
    if (path === `/accounts/${account.uuid}/`) return Promise.resolve(team);
    if (path.endsWith("/organizations/")) return Promise.resolve({ count: 1, results: [org] });
    if (path.endsWith("/organizations/org-one/")) return Promise.resolve({ ...org, description: "Original", support_email: "help@example.test", support_url: "https://example.test" });
    return Promise.resolve({ count: 0, results: [] });
  });
  const user = setupUser();
  renderRoute(<AccountAdministrationPage />);
  await user.click(await screen.findByRole("button", { name: "Team" }));
  await user.click(screen.getByRole("tab", { name: "Organizations" }));
  await user.click(await screen.findByRole("button", { name: "Division (default)" }));
  await user.clear(await screen.findByLabelText("Description"));
  await user.type(screen.getByLabelText("Description"), "Changed");
  await user.click(screen.getByRole("button", { name: "Save organization" }));
  await waitFor(() => expect(mockApi).toHaveBeenCalledWith(`/accounts/${account.uuid}/organizations/org-one/`, expect.objectContaining({ method: "PATCH", body: { description: "Changed" } })));
});

it("rechecks selected account details instead of displaying a stale collection row", async () => {
  mockApi.mockImplementation(path => {
    if (path === "/accounts/") return Promise.resolve({ count: 1, results: [{ ...account, kind: "team", name: "Previously visible" }] });
    if (path === `/accounts/${account.uuid}/`) return Promise.reject(new ApiError(403, { code: "denied", message: "Selected account denied" }));
    return Promise.resolve({ count: 0, results: [] });
  });
  const user = setupUser(); renderRoute(<AccountAdministrationPage />);
  await user.click(await screen.findByRole("button", { name: "Previously visible" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Selected account denied");
  expect(screen.queryByLabelText("Account name")).not.toBeInTheDocument();
});

it("lets a personal-account owner reach another authorized business account", async () => {
  mockApi.mockImplementation(path => {
    if (path === "/accounts/context/") return Promise.resolve({ principal_uuid: "human", individual_account: account, accounts: { count: 2, results: [account, { ...account, uuid: "business", kind: "team", name: "Business" }] }, installation_actions: [] });
    if (path === "/accounts/current/") return Promise.resolve(account);
    if (path === "/accounts/") return Promise.resolve({ count: 2, results: [account, { ...account, uuid: "business", kind: "team", name: "Business" }] });
    return Promise.resolve({ count: 0, results: [] });
  });
  const { AccountAdministrationEntry } = await import("./AccountAdministrationPage");
  const user = setupUser(); renderRoute(<AccountAdministrationEntry />);
  await screen.findByRole("heading", { name: "Personal" });
  await user.click(screen.getByRole("button", { name: "Other accounts" }));
  expect(await screen.findByRole("button", { name: "Business" })).toBeInTheDocument();
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";

import { WorkspaceAuthorizationPage } from "./WorkspaceAuthorizationPage";

const mockApi = vi.mocked(apiFetch);
const WORKSPACE = "11111111-1111-1111-1111-111111111111";
const GROUP = "22222222-2222-2222-2222-222222222222";
const POLICY = "33333333-3333-3333-3333-333333333333";
const OPERATION = "44444444-4444-4444-4444-444444444444";
let operationReads = 0;
let reconciliationWrites = 0;
let failMembership = false;
let failCreation = false;

function renderPage() {
  const router = createMemoryRouter(
    [{ path: "/administer/organization/workspaces/:workspaceUuid/policy", element: <WorkspaceAuthorizationPage /> }],
    { initialEntries: [`/administer/organization/workspaces/${WORKSPACE}/policy`] },
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.mockReset();
  operationReads = 0;
  reconciliationWrites = 0;
  failMembership = false;
  failCreation = false;
  mockApi.mockImplementation((path: string, options) => {
    if (path === "/workspaces/authorization/catalog/") {
      return Promise.resolve([
        {
          code: "workspace.manage_authorization",
          target_type: "workspace",
          administrative: true,
          delegable: true,
          principal_kinds: ["human", "service"],
        },
        {
          code: "workspace.delegate_authorization",
          target_type: "workspace",
          administrative: true,
          delegable: false,
          principal_kinds: ["human", "service"],
        },
      ]);
    }
    if (path === "/workspaces/authorization/predefined-catalog/") {
      return Promise.resolve([
        {
          code: "workspace_administrator",
          name: "Workspace Administrator",
          assignment_group_name: "Workspace Administrators",
          target_type: "workspace",
          actions: ["workspace.manage_authorization"],
        },
      ]);
    }
    if (path.endsWith("/groups/") && options?.method !== "POST") {
      return Promise.resolve([{ uuid: GROUP, name: "Operators", description: "", predefined_code: "", is_active: true }]);
    }
    if (path.endsWith("/policies/") && options?.method !== "POST") {
      return Promise.resolve([
        { uuid: POLICY, name: "Workspace admins", description: "", predefined_code: "", is_active: true },
        { uuid: "66666666-6666-6666-6666-666666666666", name: "Built-in workspace policy", description: "", predefined_code: "workspace_administrator", is_active: true },
      ]);
    }
    if (path.endsWith("/groups/") && options?.method === "POST" && failCreation) {
      return Promise.reject(new Error("internal provider failure"));
    }
    if (path.includes("/memberships/") && options?.method === "POST") {
      if (failMembership) return Promise.reject(new Error("internal provider failure"));
      return Promise.resolve({ operation_id: OPERATION, state: "unresolved" });
    }
    if (path.includes(`/operations/${OPERATION}/`)) {
      if (options?.method === "POST") {
        reconciliationWrites += 1;
        return Promise.resolve({
          uuid: OPERATION,
          relationship_kind: "group_member",
          action: "",
          effect: "grant",
          state: "confirmed",
          outcome_reason: "reconciled_primary_read",
        });
      }
      operationReads += 1;
      return Promise.resolve({
        uuid: OPERATION,
        relationship_kind: "group_member",
        action: "",
        effect: "grant",
        state: "unresolved",
        outcome_reason: "provider_outcome_unknown",
      });
    }
    return Promise.reject(new Error(`unexpected request: ${path}`));
  });
});

describe("WorkspaceAuthorizationPage", () => {
  it("renders scoped groups, policies, and the closed workspace action catalog", async () => {
    renderPage();

    expect(await screen.findByText("Policies and groups")).toBeInTheDocument();
    expect(screen.getAllByText("Operators").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Workspace admins").length).toBeGreaterThan(0);
    expect(screen.getByRole("option", { name: "workspace.manage_authorization" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Workspace Administrator" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "workspace.delegate_authorization" })).not.toBeInTheDocument();
    expect(screen.getByText("Built-in workspace policy")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Built-in workspace policy" })).not.toBeInTheDocument();
  });

  it("keeps status reads observational and uses explicit reconciliation", async () => {
    renderPage();
    await screen.findAllByText("Operators");
    fireEvent.change(screen.getByLabelText("Group"), { target: { value: GROUP } });
    fireEvent.change(screen.getAllByLabelText("Principal UUID")[0], {
      target: { value: "55555555-5555-5555-5555-555555555555" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Apply" })[0]);

    expect(await screen.findByText("Authorization change: unresolved")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reconcile status" }));

    expect(await screen.findByText("Authorization change: confirmed")).toBeInTheDocument();
    expect(mockApi.mock.calls.filter(([path]) => String(path).includes("/memberships/"))).toHaveLength(1);
    await waitFor(() => expect(operationReads).toBeGreaterThan(0));
    expect(reconciliationWrites).toBe(1);
  });

  it("shows a mutation failure without exposing provider errors", async () => {
    failMembership = true;
    renderPage();
    await screen.findAllByText("Operators");
    fireEvent.change(screen.getByLabelText("Group"), { target: { value: GROUP } });
    fireEvent.change(screen.getAllByLabelText("Principal UUID")[0], {
      target: { value: "55555555-5555-5555-5555-555555555555" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Apply" })[0]);

    expect(await screen.findByText("Authorization change could not be completed")).toBeInTheDocument();
    expect(screen.queryByText("internal provider failure")).not.toBeInTheDocument();
    expect(mockApi.mock.calls.filter(([path]) => String(path).includes("/memberships/"))).toHaveLength(1);
  });

  it("preserves the metadata draft when creation fails", async () => {
    failCreation = true;
    renderPage();
    await screen.findAllByText("Operators");
    fireEvent.change(screen.getAllByLabelText("Name")[0], { target: { value: "New operators" } });
    fireEvent.click(screen.getByRole("button", { name: "Create group" }));

    expect(await screen.findByText("Authorization change could not be completed")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Name")[0]).toHaveValue("New operators");
  });

  it.each([
    ["Group membership", "memberships"],
    ["Policy assignment", "assignments"],
    ["Predefined administrator assignment", "predefined-assignments"],
    ["Action assignment", "direct-assignments"],
    ["Action assignment", "actions"],
  ])("recovers the original %s command after its response is lost (%s)", async (title, endpoint) => {
    const normalRequest = mockApi.getMockImplementation()!;
    let acceptedCommand: unknown;
    let acceptedPath = "";
    let attempts = 0;
    mockApi.mockImplementation((path, options) => {
      if (options?.method === "POST" && path.endsWith(`/${endpoint}/`)) {
        attempts += 1;
        if (attempts === 1) {
          // The service has durably accepted this command before the response
          // disappears. It recognizes redelivery only by this exact identity.
          acceptedCommand = options.body;
          acceptedPath = path;
          return Promise.reject(new TypeError("response lost after acceptance"));
        }
        expect(path).toBe(acceptedPath);
        expect(options.body).toEqual(acceptedCommand);
        return Promise.resolve({ operation_id: OPERATION, state: "confirmed" });
      }
      return normalRequest(path, options);
    });
    renderPage();
    await screen.findByText("Policies and groups");
    const card = screen.getByRole("heading", { name: title }).parentElement!.closest("[data-slot=card]")!;
    const form = within(card as HTMLElement);
    for (const [label, value] of [
      ["Group", GROUP], ["Policy", POLICY], ["Predefined policy", "workspace_administrator"],
      ["Principal UUID", "55555555-5555-5555-5555-555555555555"],
      ["Predefined principal UUID", "55555555-5555-5555-5555-555555555555"],
      ["Action", "workspace.manage_authorization"],
    ]) {
      const input = form.queryByLabelText(label);
      if (input) fireEvent.change(input, { target: { value } });
    }
    if (endpoint === "actions") fireEvent.change(form.getByLabelText("Policy (optional)"), { target: { value: POLICY } });
    fireEvent.click(form.getByRole("button", { name: "Apply" }));
    const retry = await form.findByRole("button", { name: "Retry original command" });
    expect(form.getByRole("button", { name: "Apply" })).toBeDisabled();
    for (const input of [...form.queryAllByRole("textbox"), ...form.queryAllByRole("combobox")]) {
      expect(input).toBeDisabled();
    }
    fireEvent.click(retry);
    expect(await form.findByText("Authorization change: confirmed")).toBeInTheDocument();
    expect(attempts).toBe(2);
    expect(form.getByRole("button", { name: "Apply" })).toBeEnabled();
  });

  it("does not discard an uncertain command when a recovery attempt is rejected", async () => {
    const normalRequest = mockApi.getMockImplementation()!;
    const bodies: unknown[] = [];
    mockApi.mockImplementation((path, options) => {
      if (path.includes("/memberships/") && options?.method === "POST") {
        bodies.push(options.body);
        if (bodies.length === 1) return Promise.reject(new TypeError("lost response"));
        if (bodies.length === 2) return Promise.reject(new ApiError(403, { code: "forbidden", message: "denied" }));
        return Promise.resolve({ operation_id: OPERATION, state: "confirmed" });
      }
      return normalRequest(path, options);
    });
    renderPage();
    await screen.findByText("Policies and groups");
    fireEvent.change(screen.getByLabelText("Group"), { target: { value: GROUP } });
    fireEvent.change(screen.getAllByLabelText("Principal UUID")[0], { target: { value: POLICY } });
    fireEvent.click(screen.getAllByRole("button", { name: "Apply" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Retry original command" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    const retry = await screen.findByRole("button", { name: "Retry original command" });
    expect(screen.getByLabelText("Group")).toBeDisabled();
    fireEvent.click(retry);
    expect(await screen.findByText("Authorization change: confirmed")).toBeInTheDocument();
    expect(bodies).toEqual([bodies[0], bodies[0], bodies[0]]);
  });
});

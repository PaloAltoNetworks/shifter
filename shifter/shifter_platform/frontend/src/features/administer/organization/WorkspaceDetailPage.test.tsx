import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api/errors";
import type { Workspace } from "@/api/types";
import { setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { WorkspaceDetailPage } from "./WorkspaceDetailPage";

const mockApi = vi.mocked(apiFetch);

const WS = "11111111-1111-1111-1111-111111111111";

function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    uuid: WS,
    organization_uuid: "org-1",
    organization_name: "Acme",
    name: "Blue",
    is_personal: false,
    is_archived: false,
    archived_at: null,
    egress_policy: "status-quo",
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}

/**
 * Route apiFetch for the detail GET plus the lifecycle mutations, holding the
 * workspace state so it mutates like a real backend: a mutation returns the
 * *post-mutation* workspace (rename echoes the new name, archive/restore flip
 * `is_archived`) AND a subsequent GET reflects that same state. This lets a test
 * assert the success-path UI update — including the one the hook's `onSuccess`
 * cache invalidation refetches — not merely that the call was made.
 */
function stubApi(initial: Workspace | ApiError) {
  if (initial instanceof ApiError) {
    mockApi.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === `/workspaces/${WS}/` && (options?.method ?? "GET") === "GET") return Promise.reject(initial);
      return Promise.reject(new ApiError(404, { code: "not_found", message: "nope" }));
    });
    return;
  }
  let current = initial;
  mockApi.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET";
    if (path === `/workspaces/${WS}/` && method === "GET") return Promise.resolve(current);
    if (path === `/workspaces/${WS}/` && method === "PATCH") {
      const body = options?.body as { name?: string } | undefined;
      current = workspace({ ...current, name: body?.name ?? current.name });
      return Promise.resolve(current);
    }
    if (path === `/workspaces/${WS}/archive/`) {
      current = workspace({ ...current, is_archived: true, archived_at: "2026-03-01T00:00:00Z" });
      return Promise.resolve(current);
    }
    if (path === `/workspaces/${WS}/restore/`) {
      current = workspace({ ...current, is_archived: false, archived_at: null });
      return Promise.resolve(current);
    }
    if (path === `/workspaces/${WS}/egress-policy/` && method === "PUT") {
      const body = options?.body as { egress_policy?: Workspace["egress_policy"] } | undefined;
      current = workspace({ ...current, egress_policy: body?.egress_policy ?? current.egress_policy });
      return Promise.resolve(current);
    }
    if (path === `/workspaces/${WS}/transfer/`) return Promise.resolve(current);
    return Promise.reject(new ApiError(404, { code: "not_found", message: "nope" }));
  });
}

function renderDetail() {
  const router = createMemoryRouter(
    [{ path: "/administer/organization/workspaces/:workspaceUuid", element: <WorkspaceDetailPage /> }],
    { initialEntries: [`/administer/organization/workspaces/${WS}`] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("WorkspaceDetailPage", () => {
  it("renders the workspace overview", async () => {
    stubApi(workspace());
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Blue" })).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("renders a denied state on 403", async () => {
    stubApi(new ApiError(403, { code: "forbidden", message: "no" }));
    renderDetail();
    expect(await screen.findByText("You do not have permission to view this workspace")).toBeInTheDocument();
  });

  it("renders a not-found state on 404", async () => {
    stubApi(new ApiError(404, { code: "not_found", message: "gone" }));
    renderDetail();
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
  });

  it("renames the workspace through the API", async () => {
    const user = setupUser();
    stubApi(workspace());
    renderDetail();
    const input = await screen.findByLabelText("Name");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.click(screen.getByRole("button", { name: "Rename" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/`,
        expect.objectContaining({ method: "PATCH", body: { name: "Renamed" } }),
      ),
    );
    // Success effect: onSuccess seeds the fresh snapshot — the "Saved." marker
    // shows and the page heading reflects the new name.
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Renamed" })).toBeInTheDocument();
  });

  it("shows the current network egress policy and disables save until it changes", async () => {
    stubApi(workspace({ egress_policy: "none" }));
    renderDetail();
    await screen.findByRole("heading", { name: "Blue" });
    // The posture renders (overview detail + the select's current value).
    expect(screen.getAllByText("Zero egress (no outbound NAT path)").length).toBeGreaterThan(0);
    // Save is disabled while the selection equals the persisted value.
    expect(screen.getByRole("button", { name: "Save egress policy" })).toBeDisabled();
  });

  it("sets the workspace egress policy through the API", async () => {
    const user = setupUser();
    stubApi(workspace({ egress_policy: "status-quo" }));
    renderDetail();
    await screen.findByRole("heading", { name: "Blue" });

    await user.click(screen.getByRole("combobox", { name: "Network egress policy" }));
    await user.click(await screen.findByRole("option", { name: "Zero egress (no outbound NAT path)" }));
    await user.click(screen.getByRole("button", { name: "Save egress policy" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/egress-policy/`,
        expect.objectContaining({ method: "PUT", body: { egress_policy: "none" } }),
      ),
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    // Only correct via the hook's onSuccess cache write: the fresh snapshot has
    // egress_policy="none", so the selection now equals the persisted value and
    // the Save button disables again. A broken cache write would leave it enabled
    // (the UI showing a stale policy after "saving").
    await waitFor(() => expect(screen.getByRole("button", { name: "Save egress policy" })).toBeDisabled());
  });

  it("archives the workspace after confirmation", async () => {
    const user = setupUser();
    stubApi(workspace());
    renderDetail();
    await screen.findByRole("heading", { name: "Blue" });
    await user.click(screen.getByRole("button", { name: "Archive" }));

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Archive" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(`/workspaces/${WS}/archive/`, expect.objectContaining({ method: "POST" })),
    );
    // Success effect: the confirm dialog closes and the UI flips to the archived
    // state (the action button now offers Restore).
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
  });

  it("restores an archived workspace after confirmation", async () => {
    const user = setupUser();
    stubApi(workspace({ is_archived: true, archived_at: "2026-03-01T00:00:00Z" }));
    renderDetail();
    await screen.findByRole("heading", { name: "Blue" });
    await user.click(screen.getByRole("button", { name: "Restore" }));

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Restore" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(`/workspaces/${WS}/restore/`, expect.objectContaining({ method: "POST" })),
    );
    // Success effect: the confirm dialog closes and the UI flips back to active
    // (the action button now offers Archive).
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
  });

  it("transfers ownership through the API", async () => {
    const user = setupUser();
    stubApi(workspace());
    renderDetail();
    await user.type(await screen.findByLabelText("New owner user ID"), "42");
    await user.click(screen.getByRole("button", { name: "Transfer ownership" }));

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Transfer" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/transfer/`,
        expect.objectContaining({ method: "POST", body: { user_id: 42 } }),
      ),
    );
    // Success effect: the confirm dialog closes and the user-id field resets.
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByLabelText("New owner user ID")).toHaveValue(null);
  });

  it("has no axe violations when loaded", async () => {
    stubApi(workspace());
    const { container } = renderDetail();
    await screen.findByRole("heading", { name: "Blue" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

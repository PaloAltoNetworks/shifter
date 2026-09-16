import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api/errors";
import type { OrganizationProfile } from "@/api/types";
import { setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { OrganizationSettingsDetailPage, OrganizationSettingsPage } from "./OrganizationSettingsPage";

const mockApi = vi.mocked(apiFetch);

const ORG_UUID = "org-uuid-1";

function profile(overrides: Partial<OrganizationProfile> = {}): OrganizationProfile {
  return {
    uuid: ORG_UUID,
    name: "Acme",
    description: "Original description",
    support_email: "help@acme.test",
    support_url: "https://acme.test/support",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  } as OrganizationProfile;
}

function orgListPage(orgs: Array<{ uuid: string; name: string }>) {
  return {
    count: orgs.length,
    next: null,
    previous: null,
    results: orgs.map((o) => profile({ uuid: o.uuid, name: o.name })),
  };
}

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderEditor() {
  const router = createMemoryRouter(
    [{ path: "/administer/organization/settings/:organizationUuid", element: <OrganizationSettingsDetailPage /> }],
    { initialEntries: [`/administer/organization/settings/${ORG_UUID}`] },
  );
  return render(
    <QueryClientProvider client={client()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function renderChooser() {
  const router = createMemoryRouter(
    [
      { path: "/administer/organization/settings", element: <OrganizationSettingsPage /> },
      { path: "/administer/organization/settings/:organizationUuid", element: <div>editor for org</div> },
    ],
    { initialEntries: ["/administer/organization/settings"] },
  );
  return render(
    <QueryClientProvider client={client()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("OrganizationSettingsDetailPage", () => {
  it("loads and displays the organization profile", async () => {
    mockApi.mockResolvedValueOnce(profile());

    renderEditor();

    expect(await screen.findByDisplayValue("Acme")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Original description")).toBeInTheDocument();
    expect(screen.getByDisplayValue("help@acme.test")).toBeInTheDocument();
  });

  it("saves edited fields and shows a success confirmation", async () => {
    const user = setupUser();
    mockApi.mockResolvedValueOnce(profile());
    renderEditor();
    await screen.findByDisplayValue("Acme");

    mockApi.mockResolvedValueOnce(profile({ description: "New description" }));
    await user.clear(screen.getByLabelText(/description/i));
    await user.type(screen.getByLabelText(/description/i), "New description");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const patch = mockApi.mock.calls.find(([, opts]) => (opts as { method?: string })?.method === "PATCH");
      expect(patch).toBeTruthy();
      const body = (patch![1] as { body: Record<string, unknown> }).body;
      expect(body.description).toBe("New description");
      // Only the changed field is sent — untouched fields must be absent so a
      // stale form cannot revert another admin's concurrent edit to them.
      expect(Object.keys(body)).toEqual(["description"]);
    });
    expect(await screen.findByText(/saved/i)).toBeInTheDocument();
  });

  it("surfaces a server field error", async () => {
    const user = setupUser();
    mockApi.mockResolvedValueOnce(profile());
    renderEditor();
    await screen.findByDisplayValue("Acme");

    mockApi.mockRejectedValueOnce(
      new ApiError(400, { code: "validation_error", message: "Invalid", details: { support_email: ["Enter a valid email address."] } }),
    );
    await user.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText(/enter a valid email address/i)).toBeInTheDocument();
  });

  it("shows an access-denied state on 403", async () => {
    mockApi.mockRejectedValueOnce(new ApiError(403, { code: "organization_access_denied", message: "Organization access denied" }));

    renderEditor();

    expect(await screen.findByText(/do not have permission/i)).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    mockApi.mockResolvedValueOnce(profile());
    const { container } = renderEditor();
    await screen.findByDisplayValue("Acme");

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

describe("OrganizationSettingsPage chooser", () => {
  it("lists each administrable organization when there is more than one", async () => {
    mockApi.mockResolvedValueOnce(
      orgListPage([
        { uuid: "org-a", name: "Alpha" },
        { uuid: "org-b", name: "Beta" },
      ]),
    );

    renderChooser();

    expect(await screen.findByRole("link", { name: /alpha/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /beta/i })).toBeInTheDocument();
  });

  it("opens the single administrable organization directly", async () => {
    mockApi.mockResolvedValueOnce(orgListPage([{ uuid: "org-a", name: "Alpha" }]));

    renderChooser();

    expect(await screen.findByText("editor for org")).toBeInTheDocument();
  });

  it("shows an honest empty state when the actor administers none", async () => {
    mockApi.mockResolvedValueOnce(orgListPage([]));

    renderChooser();

    expect(await screen.findByText(/no organizations available/i)).toBeInTheDocument();
  });
});

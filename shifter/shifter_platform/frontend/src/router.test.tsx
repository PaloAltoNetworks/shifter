import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/bootstrap", () => ({ useBootstrap: vi.fn() }));

import { useBootstrap } from "@/api/bootstrap";
import { platformSettingsPath } from "@/features/administer/routes";
import { STAFF_BOOTSTRAP } from "@/test/utils";

import { router } from "./router";

const mockUseBootstrap = vi.mocked(useBootstrap);

interface RouteNode {
  readonly path?: string;
  readonly handle?: { readonly permissionPolicy?: string };
  readonly children?: readonly RouteNode[];
}

function collectPaths(routes: readonly RouteNode[]): string[] {
  const out: string[] = [];
  for (const route of routes) {
    if (route.path) out.push(route.path);
    if (route.children) out.push(...collectPaths(route.children));
  }
  return out;
}

beforeEach(() => {
  mockUseBootstrap.mockReset();
  mockUseBootstrap.mockReturnValue({ data: STAFF_BOOTSTRAP, isLoading: false, error: null } as ReturnType<
    typeof useBootstrap
  >);
});

describe("router", () => {
  it("mounts a single root route hosting the workspace layout", () => {
    expect(router.routes).toHaveLength(1);
    expect((router.routes[0] as RouteNode).path).toBe("/");
  });

  it("registers every top-level workspace group so deep links resolve", () => {
    const paths = collectPaths(router.routes as readonly RouteNode[]);
    for (const group of [
      "mission-control",
      "scenario-editor",
      "ctf",
      "ctf/admin",
      "raes-image-registry",
      "administer",
    ]) {
      expect(paths).toContain(group);
    }
  });

  it("registers a catch-all not-found route so an unknown path never dead-ends", () => {
    expect(collectPaths(router.routes as readonly RouteNode[])).toContain("*");
  });

  it("carries the advisory permission handle on each gated group", () => {
    const root = router.routes[0] as RouteNode;
    const group = (path: string) => root.children?.find((child) => child.path === path);

    expect(group("mission-control")?.handle?.permissionPolicy).toBe("authenticated");
    expect(group("scenario-editor")?.handle?.permissionPolicy).toBe("threat_research");
    expect(group("raes-image-registry")?.handle?.permissionPolicy).toBe("threat_research");
    expect(group("administer")?.handle?.permissionPolicy).toBe("staff");
    expect(group("ctf")?.handle?.permissionPolicy).toBe("ctf_participant");
    expect(group("ctf/admin")?.handle?.permissionPolicy).toBe("ctf_organizer");
  });

  it("nests the scoped workspace surfaces under the organization console", () => {
    const paths = collectPaths(router.routes as readonly RouteNode[]);
    expect(paths).toContain("organization");
    expect(paths).toContain("workspaces/:workspaceUuid");
    // The dynamic per-workspace surfaces are generated from WORKSPACE_SURFACES.
    expect(paths).toContain("membership");
  });

  it("redirects the legacy Mission Control settings URL to the staff-owned page", async () => {
    const memoryRouter = createMemoryRouter(router.routes, {
      initialEntries: ["/mission-control/settings/"],
    });

    render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={memoryRouter} />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Platform settings" })).toBeInTheDocument();
    await waitFor(() => expect(memoryRouter.state.location.pathname).toBe(platformSettingsPath()));
  });

  it("preserves the staff gate when a non-staff user follows the legacy settings URL", async () => {
    mockUseBootstrap.mockReturnValue({
      data: {
        ...STAFF_BOOTSTRAP,
        principal: { ...STAFF_BOOTSTRAP.principal, is_staff: false },
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useBootstrap>);
    const memoryRouter = createMemoryRouter(router.routes, {
      initialEntries: ["/mission-control/settings/"],
    });

    render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={memoryRouter} />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Access denied" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Platform settings" })).not.toBeInTheDocument();
    await waitFor(() => expect(memoryRouter.state.location.pathname).toBe(platformSettingsPath()));
  });
});

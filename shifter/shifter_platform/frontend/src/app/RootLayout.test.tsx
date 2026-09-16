import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/bootstrap", () => ({ useBootstrap: vi.fn() }));

import { useBootstrap } from "@/api/bootstrap";
import { STAFF_BOOTSTRAP } from "@/test/utils";

import { RootLayout, type RouteHandle } from "./RootLayout";

const mockUseBootstrap = vi.mocked(useBootstrap);

/** Render RootLayout as the shell over a single child route carrying `handle`. */
function renderWithHandle(handle: RouteHandle) {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <RootLayout />,
        children: [{ path: "area", handle, element: <div>Area content</div> }],
      },
    ],
    { initialEntries: ["/area"] },
  );
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockUseBootstrap.mockReset();
  mockUseBootstrap.mockReturnValue({ data: STAFF_BOOTSTRAP, isLoading: false, error: null } as ReturnType<
    typeof useBootstrap
  >);
});

describe("RootLayout route gating", () => {
  it("renders the matched route when the advisory policy allows the principal", async () => {
    renderWithHandle({ permissionPolicy: "staff" });
    expect(await screen.findByText("Area content")).toBeInTheDocument();
  });

  it("renders the shared Access denied state when the advisory policy denies the principal", async () => {
    // STAFF_BOOTSTRAP has can_access_threat_research: false.
    renderWithHandle({ permissionPolicy: "threat_research" });
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByText("Area content")).not.toBeInTheDocument();
  });

  it("renders the route when it carries no advisory policy", async () => {
    renderWithHandle({});
    expect(await screen.findByText("Area content")).toBeInTheDocument();
  });
});

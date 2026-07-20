import type { ReactElement } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import type { Bootstrap } from "@/api/types";

export const STAFF_BOOTSTRAP: Bootstrap = {
  principal: {
    id: 1,
    username: "staff",
    display_name: "Staff User",
    is_authenticated: true,
    is_staff: true,
    is_superuser: false,
  },
  permissions: {
    can_access_risk_register: true,
    can_access_threat_research: false,
    is_ctf_organizer: false,
    is_ctf_participant: false,
    can_view_users: true,
    can_change_users: true,
    can_delete_users: true,
  },
  modes: { participant: false, operator: true, default: "operator" },
  feature_flags: {
    risk_register_spa: true,
    platform_spa: true,
    mission_control_spa: true,
    scenario_editor_spa: true,
    ctf_workspace_spa: true,
    aces_native_provisioning: true,
    administer_spa: true,
  },
};

function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

export function renderRoute(
  element: ReactElement,
  { path = "/", initialEntries = ["/"] }: { path?: string; initialEntries?: string[] } = {},
): RenderResult {
  const router = createMemoryRouter([{ path, element }], { initialEntries });
  return render(
    <QueryClientProvider client={testQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

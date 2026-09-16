import type { ReactElement } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";

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
    can_access_threat_research: false,
    is_ctf_organizer: false,
    is_ctf_participant: false,
    can_administer_ctf: false,
    can_view_users: true,
    can_change_users: true,
    can_delete_users: true,
  },
  modes: { participant: false, operator: true, default: "operator" },
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

/**
 * Canonical user-event setup for component tests. `delay: null` removes the
 * default per-keystroke `setTimeout` yield, which under full-suite CPU
 * contention can amplify a form-heavy test past vitest's `testTimeout` (see
 * issue #1878). Use for typing-heavy tests; the default `userEvent.setup()`
 * remains fine for click-only interactions.
 */
export function setupUser(): UserEvent {
  return userEvent.setup({ delay: null });
}

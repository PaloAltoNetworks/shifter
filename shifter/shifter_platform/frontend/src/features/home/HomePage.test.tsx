import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { Bootstrap, DashboardSummary } from "@/api/types";
import { STAFF_BOOTSTRAP } from "@/test/utils";

let currentBootstrap: Bootstrap = STAFF_BOOTSTRAP;

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => currentBootstrap,
}));
vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { ModeProvider } from "@/app/mode";
import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";

import { HomePage } from "./HomePage";

const mockApi = vi.mocked(apiFetch);

const SUMMARY: DashboardSummary = {
  active_range: { present: true, status: "running" },
  active_event: { present: false, name: null },
  risk_register: { accessible: true, open_count: 3 },
};

function renderHome(bootstrap: Bootstrap = STAFF_BOOTSTRAP) {
  currentBootstrap = bootstrap;
  // The dashboard hook sets retry:1; keep the single retry instant so the error
  // state settles within the test timeout.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ModeProvider bootstrap={bootstrap}>
          <HomePage />
        </ModeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.mockReset();
  currentBootstrap = STAFF_BOOTSTRAP;
});

describe("HomePage (operator)", () => {
  it("renders the operational summary from the dashboard read", async () => {
    mockApi.mockResolvedValue(SUMMARY);
    renderHome();
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText("No active event")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Risk Register/ })).toHaveAttribute("href", "/risk-register");
  });

  it("surfaces a safe error state with the request id", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "server_error", message: "boom", request_id: "req-123" }));
    renderHome();
    expect(await screen.findByText(/Unable to load the dashboard/)).toBeInTheDocument();
    expect(screen.getByText(/req-123/)).toBeInTheDocument();
  });
});

describe("HomePage (participant)", () => {
  it("renders a participant landing without calling the dashboard read", () => {
    renderHome({
      ...STAFF_BOOTSTRAP,
      modes: { participant: true, operator: false, default: "participant" },
    });
    expect(screen.getByText("Your event")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Challenges/ })).toHaveAttribute("href", "/ctf/challenges/");
    expect(mockApi).not.toHaveBeenCalled();
  });
});

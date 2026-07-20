import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { AdminUserDetail } from "@/api/types";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { adminUser, pageOf } from "./test-fixtures";
import { UsersListPage } from "./UsersListPage";

const mockApi = vi.mocked(apiFetch);

const userRow = (overrides: Partial<AdminUserDetail> = {}) =>
  adminUser({ account_origin: "provider", is_staff: true, ...overrides });

beforeEach(() => {
  mockApi.mockReset();
});

describe("UsersListPage", () => {
  it("renders loaded users with origin and roles", async () => {
    mockApi.mockResolvedValue(pageOf([userRow({ is_superuser: true })]));
    renderRoute(<UsersListPage />);
    expect(await screen.findByText("Alice Example")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Provider")).toBeInTheDocument();
    expect(within(table).getByText("Superuser")).toBeInTheDocument();
  });

  it("distinguishes the initial empty state", async () => {
    mockApi.mockResolvedValue(pageOf([]));
    renderRoute(<UsersListPage />);
    expect(await screen.findByText("No users yet")).toBeInTheDocument();
  });

  it("renders a permission-denied state on 403", async () => {
    mockApi.mockRejectedValue(new ApiError(403, { code: "forbidden", message: "no" }));
    renderRoute(<UsersListPage />);
    expect(await screen.findByText("You do not have permission to view users")).toBeInTheDocument();
  });

  it("renders a generic error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<UsersListPage />);
    expect(await screen.findByText("Could not load users")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(pageOf([userRow()]));
    const { container } = renderRoute(<UsersListPage />);
    await screen.findByText("Alice Example");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

const api = vi.hoisted(() => ({
  query: vi.fn(),
  replaceTenant: vi.fn(),
  resetTenant: vi.fn(),
  replaceGroup: vi.fn(),
  resetGroup: vi.fn(),
  replaceTenantError: null as Error | null,
}));

vi.mock("@/api/administer", () => ({
  useMissionControlLeasePolicySettings: api.query,
  useReplaceTenantLeasePolicy: () => ({
    mutate: api.replaceTenant,
    isPending: false,
    error: api.replaceTenantError,
    reset: vi.fn(),
  }),
  useResetTenantLeasePolicy: () => ({ mutate: api.resetTenant, isPending: false, error: null, reset: vi.fn() }),
  useReplaceGroupLeasePolicy: () => ({ mutate: api.replaceGroup, isPending: false, error: null, reset: vi.fn() }),
  useResetGroupLeasePolicy: () => ({ mutate: api.resetGroup, isPending: false, error: null, reset: vi.fn() }),
}));

const policy = {
  initial_days: 30,
  extension_days: 30,
  maximum_days: 365,
  extensions_enabled: true,
};

function settings(tenantOverride: { policy: typeof policy; revision: number } | null = null) {
  return {
    baseline: policy,
    tenant_revision: tenantOverride?.revision ?? 0,
    tenant_override: tenantOverride,
    effective_tenant: tenantOverride?.policy ?? policy,
    effective_source: tenantOverride ? ("runtime" as const) : ("deployment" as const),
    groups: [{ id: 7, name: "Blue Team", revision: 0, override: null }],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.replaceTenantError = null;
  api.query.mockReturnValue({ data: settings(), isLoading: false, isError: false, error: null });
});

import { PlatformSettingsPage } from "./PlatformSettingsPage";

describe("PlatformSettingsPage", () => {
  it("shows baseline, effective source, and policy-eligible groups", () => {
    render(<PlatformSettingsPage />);

    expect(screen.getByRole("heading", { name: "Mission Control lease policy" })).toBeInTheDocument();
    expect(screen.getByText("Deployment fallback")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Blue Team" })).toBeInTheDocument();
    expect(screen.getByText(/new generations only/i)).toBeInTheDocument();
  });

  it("submits a complete tenant replacement with the revision currently displayed", async () => {
    const user = userEvent.setup();
    render(<PlatformSettingsPage />);
    const tenant = screen.getByTestId("tenant-lease-policy");
    const initial = tenant.querySelector<HTMLInputElement>("#tenant-initial-days")!;
    await user.clear(initial);
    await user.type(initial, "14");
    await user.click(screen.getByRole("button", { name: "Save tenant policy" }));

    expect(api.replaceTenant).toHaveBeenCalledWith({
      expected_revision: 0,
      initial_days: 14,
      extension_days: 30,
      maximum_days: 365,
      extensions_enabled: true,
    });
  });

  it("uses explicit reset for an existing tenant override", async () => {
    const user = userEvent.setup();
    api.query.mockReturnValue({
      data: settings({ policy: { ...policy, maximum_days: 180 }, revision: 3 }),
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<PlatformSettingsPage />);

    await user.click(screen.getByRole("button", { name: "Reset tenant policy" }));

    expect(api.resetTenant).toHaveBeenCalledWith({ expected_revision: 3 });
  });

  it("submits a complete group replacement using inherited tenant values", async () => {
    const user = userEvent.setup();
    render(<PlatformSettingsPage />);
    const group = screen.getByTestId("group-lease-policy-7");
    const maximum = group.querySelector<HTMLInputElement>("#group-7-maximum-days")!;
    await user.clear(maximum);
    await user.type(maximum, "90");
    await user.click(screen.getByRole("button", { name: "Save Blue Team policy" }));

    expect(api.replaceGroup).toHaveBeenCalledWith({
      expected_revision: 0,
      initial_days: 30,
      extension_days: 30,
      maximum_days: 90,
      extensions_enabled: true,
    });
  });

  it("uses explicit reset for an existing group override", async () => {
    const user = userEvent.setup();
    api.query.mockReturnValue({
      data: {
        ...settings(),
        groups: [
          {
            id: 7,
            name: "Blue Team",
            revision: 4,
            override: { policy: { ...policy, maximum_days: 90 }, revision: 4 },
          },
        ],
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<PlatformSettingsPage />);

    await user.click(screen.getByRole("button", { name: "Reset Blue Team policy" }));

    expect(api.resetGroup).toHaveBeenCalledWith({ expected_revision: 4 });
  });

  it("rejects invalid local duration bounds before mutation", async () => {
    const user = userEvent.setup();
    render(<PlatformSettingsPage />);
    const tenant = screen.getByTestId("tenant-lease-policy");
    const initial = tenant.querySelector<HTMLInputElement>("#tenant-initial-days")!;
    await user.clear(initial);
    await user.type(initial, "400");
    await user.click(screen.getByRole("button", { name: "Save tenant policy" }));

    expect(screen.getByText("Initial days cannot exceed maximum days.")).toBeInTheDocument();
    expect(api.replaceTenant).not.toHaveBeenCalled();
  });

  it("bounds unexpected mutation failures", () => {
    api.replaceTenantError = new Error("database internals");
    render(<PlatformSettingsPage />);

    expect(screen.getByText("Could not update tenant policy.")).toBeInTheDocument();
    expect(screen.queryByText("database internals")).not.toBeInTheDocument();
  });

  it("renders a bounded load error", () => {
    api.query.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: new Error("boom") });
    render(<PlatformSettingsPage />);

    expect(screen.getByText("Could not load lease policy")).toBeInTheDocument();
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = render(<PlatformSettingsPage />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

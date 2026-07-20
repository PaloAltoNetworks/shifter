import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => ({
    principal: { id: 1, username: "root", display_name: "Root", is_authenticated: true, is_staff: true, is_superuser: true },
    permissions: {},
    feature_flags: { administer_spa: true, platform_spa: true, risk_register_spa: false },
  }),
}));

import { PlatformSettingsPage } from "./PlatformSettingsPage";

describe("PlatformSettingsPage", () => {
  it("presents rollout flags as read-only, deployment-managed state", () => {
    render(<PlatformSettingsPage />);
    expect(screen.getByText("Managed by deployment")).toBeInTheDocument();
    expect(screen.getByText("Administer spa")).toBeInTheDocument();
    expect(screen.getAllByText("Enabled").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
  });

  it("has no axe violations", async () => {
    const { container } = render(<PlatformSettingsPage />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

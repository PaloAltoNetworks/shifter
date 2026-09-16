import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { axe } from "vitest-axe";

import type { Bootstrap } from "@/api/types";
import { STAFF_BOOTSTRAP } from "@/test/utils";

let currentBootstrap: Bootstrap = STAFF_BOOTSTRAP;

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => currentBootstrap,
}));

import { ModeProvider } from "@/app/mode";

import { AppShell } from "./app-shell";

function renderShell(bootstrap: Bootstrap = STAFF_BOOTSTRAP) {
  currentBootstrap = bootstrap;
  return render(
    <MemoryRouter>
      <ModeProvider bootstrap={bootstrap}>
        <AppShell>
          <h1>Page content</h1>
        </AppShell>
      </ModeProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  currentBootstrap = STAFF_BOOTSTRAP;
});

describe("AppShell", () => {
  it("renders the skip link and core landmarks", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("renders operator nav groups from the shared contract", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toHaveTextContent("Operate");
    expect(nav).toHaveTextContent("Overview");
  });

  it("links not-yet-migrated surfaces to their legacy Django route (full-page nav)", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /Ranges/ })).toHaveAttribute("href", "/mission-control/");
  });

  it("offers a POST logout form", () => {
    renderShell();
    const button = screen.getByRole("button", { name: /log out/i });
    const form = button.closest("form");
    expect(form).toHaveAttribute("action", "/logout/");
    expect(form).toHaveAttribute("method", "post");
  });

  it("hides the mode switch when only one mode is eligible", () => {
    renderShell();
    expect(screen.queryByRole("group", { name: "Mode" })).not.toBeInTheDocument();
  });

  it("shows the mode switch when both modes are eligible", () => {
    renderShell({
      ...STAFF_BOOTSTRAP,
      modes: { participant: true, operator: true, default: "operator" },
    });
    expect(screen.getByRole("group", { name: "Mode" })).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = renderShell();
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { CostPage } from "./CostPage";

describe("CostPage", () => {
  it("renders a truthful unavailable state without any cost figures", () => {
    render(<CostPage />);
    expect(screen.getByText("Cost reporting is not available yet")).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = render(<CostPage />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

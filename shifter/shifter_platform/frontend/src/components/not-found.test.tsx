import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderRoute } from "@/test/utils";

import { NotFoundPage } from "./not-found";

describe("NotFoundPage", () => {
  it("renders a recoverable not-found state", () => {
    renderRoute(<NotFoundPage />);
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });

  it("offers a link back to home", () => {
    renderRoute(<NotFoundPage />);
    const link = screen.getByRole("link", { name: "Back to home" });
    expect(link).toHaveAttribute("href", "/");
  });
});

import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";

/**
 * The `Select` wrapper drops Radix's empty-value echo (see the docstring on
 * `Select`). The regression test for that guard is
 * `features/ctf/admin/ChallengeFormPage.test.tsx::round-trips visibility,
 * target instance, and target port on save` — it exercises a real async
 * hydration and genuinely fails when the guard is removed (verified by
 * deleting the guard and re-running it).
 *
 * A synthetic reproduction was attempted here and rejected: with the items
 * rendered up front, or with the value hydrated to an unrendered item, the
 * bubble-input race does not occur and the test passes with or without the
 * guard — i.e. it asserts nothing. Rather than keep a test that cannot detect
 * the defect it names, the coverage below is limited to the property this file
 * can honestly assert: that the filter does not swallow real selections.
 */
function Visibility({ onValueChange }: Readonly<{ onValueChange: (value: string) => void }>) {
  const [value, setValue] = useState("visible");
  return (
    <Select
      value={value}
      onValueChange={(next) => {
        setValue(next);
        onValueChange(next);
      }}
    >
      <SelectTrigger aria-label="Visibility">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="visible">visible</SelectItem>
        <SelectItem value="hidden">hidden</SelectItem>
        <SelectItem value="locked">locked</SelectItem>
      </SelectContent>
    </Select>
  );
}

// Radix Select drives pointer capture and scrolling, which jsdom does not implement.
beforeAll(() => {
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
  window.HTMLElement.prototype.releasePointerCapture = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe("Select", () => {
  it("reports a real user selection through the empty-value filter", async () => {
    const onValueChange = vi.fn();
    const user = userEvent.setup({ delay: null });
    render(<Visibility onValueChange={onValueChange} />);

    await user.click(screen.getByRole("combobox", { name: "Visibility" }));
    await user.click(await screen.findByRole("option", { name: "locked" }));

    expect(onValueChange).toHaveBeenCalledWith("locked");
  });
});

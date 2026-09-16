import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { GceImageNameSchema } from "./schemas.js";

describe("GceImageNameSchema", () => {
  it("accepts exact GCE candidate names", () => {
    assert.equal(
      GceImageNameSchema.parse("shifter-polaris-vm-20260720014252"),
      "shifter-polaris-vm-20260720014252",
    );
  });

  it("rejects paths, shell syntax, uppercase, and overlong names", () => {
    for (const value of [
      "projects/p/global/images/x",
      "image;echo-pwned",
      "Image",
      `a${"b".repeat(63)}`,
    ]) {
      assert.throws(() => GceImageNameSchema.parse(value));
    }
  });
});

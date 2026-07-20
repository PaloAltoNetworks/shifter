// Behavioral guard for the AMI dispatcher's protected-ref boundary (#1656).
//
// resolveProtectedAmiRef is unit-tested directly in lib.test.js; this test
// pins the *wiring* in triggerAmiWorkflow, which regressed once already: PR1
// wired the gate in the pre-split mcp/ops/index.js, then the #690 module split
// re-created triggerAmiWorkflow in github-actions.js on the unprotected
// `ref ?? resolveGitRef(...)` path. A non-protected ref must be rejected before
// any workflow_dispatch is emitted, so a feature-branch copy cannot be used to
// weaken its own inline dev|main gate.

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { triggerAmiWorkflow } from "./github-actions.js";

describe("triggerAmiWorkflow protected-ref dispatch (#1656)", () => {
  it("rejects non-protected / injected refs before dispatching", () => {
    for (const bad of [
      "feature-x",
      "1656-harden-packer-privilege",
      "refs/tags/dev",
      "dev; rm -rf /",
      "",
    ]) {
      assert.throws(
        () =>
          triggerAmiWorkflow({
            workflow: "packer.yml",
            ami_type: "kali",
            ref: bad,
            actionsPath: "packer.yml",
          }),
        /protected branch/,
        `expected ref '${bad}' to be rejected before dispatch`,
      );
    }
  });
});

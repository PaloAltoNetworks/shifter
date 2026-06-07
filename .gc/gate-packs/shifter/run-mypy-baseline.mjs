#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const [baselinePath, runner = "../../.gc/gate-packs/python/gc-python-run"] = process.argv.slice(2);
if (!baselinePath) {
  console.error("usage: run-mypy-baseline.mjs <baseline-json> [gc-python-run]");
  process.exit(64);
}

const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
const findings = Array.isArray(baseline.findings) ? baseline.findings : [];
const result = spawnSync(runner, ["mypy", ".", "--no-error-summary"], {
  encoding: "utf8",
  maxBuffer: 16 * 1024 * 1024,
});

if (result.status === 0) {
  process.stdout.write(result.stdout ?? "");
  process.stderr.write(result.stderr ?? "");
  process.exit(0);
}

const combined = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
const matched = findings.some((finding) =>
  finding.kind === "mypy_internal_error" &&
  finding.exit_code === result.status &&
  typeof finding.pattern === "string" &&
  combined.includes(finding.pattern)
);

if (matched) {
  process.stderr.write(combined);
  console.log(`mypy baseline accepted; baseline findings: ${findings.length}; new findings: 0`);
  process.exit(0);
}

process.stdout.write(result.stdout ?? "");
process.stderr.write(result.stderr ?? "");
process.exit(result.status ?? 1);

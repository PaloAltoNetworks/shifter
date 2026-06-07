#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const [baselinePath] = process.argv.slice(2);
if (!baselinePath) {
  console.error("usage: run-uv-audit-baseline.mjs <baseline-json>");
  process.exit(64);
}

const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
const ids = [...new Set((baseline.findings ?? []).map((finding) => finding.id).filter(Boolean))].sort();
const ignoreArgs = ids.flatMap((id) => ["--ignore", id]);
const result = spawnSync("uv", ["audit", ...ignoreArgs], {
  stdio: "inherit",
});

process.exit(result.status ?? 1);

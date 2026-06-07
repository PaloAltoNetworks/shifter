#!/usr/bin/env node
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const args = new Set(process.argv.slice(2));
const repoRoot = process.cwd();
const baselinePath = ".gc/baselines/docs-generic.json";
const skipDirs = new Set([
  ".git",
  ".gc",
  ".venv",
  "venv",
  "env",
  "node_modules",
  "build",
  "dist",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  ".terraform",
  ".tox",
  ".nox",
  "coverage",
]);

function repoRelative(path) {
  return relative(repoRoot, path).split(sep).join("/");
}

function loadBaseline() {
  if (!existsSync(baselinePath)) return new Set();
  const parsed = JSON.parse(readFileSync(baselinePath, "utf8"));
  return new Set((parsed.findings ?? []).map((finding) => `${finding.rule}\t${finding.path}`));
}

function isProbablyText(buffer) {
  if (buffer.includes(0)) return false;
  return true;
}

function walk(dir, visit) {
  for (const entry of readdirSync(dir)) {
    if (skipDirs.has(entry)) continue;
    const path = join(dir, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      walk(path, visit);
    } else if (stat.isFile()) {
      visit(path);
    }
  }
}

function collectContentFindings() {
  const findings = [];
  walk(repoRoot, (path) => {
    const buffer = readFileSync(path);
    if (!isProbablyText(buffer)) return;
    const text = buffer.toString("utf8");
    const rel = repoRelative(path);
    if (!args.has("--secrets-only") && /(^|\n)TODO(\b|:)/.test(text)) {
      findings.push({ rule: "todo_marker", path: rel });
    }
    if (/-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----/.test(text)) {
      findings.push({ rule: "private_key_marker", path: rel });
    }
  });
  return findings;
}

function collectWorkflowFindings() {
  const root = join(repoRoot, ".github", "workflows");
  const findings = [];
  if (!existsSync(root)) return findings;
  walk(root, (path) => {
    if (!/\.ya?ml$/.test(path)) return;
    const text = readFileSync(path, "utf8");
    const rel = repoRelative(path);
    for (const match of text.matchAll(/uses:\s*([^@\s]+)\s*$/gm)) {
      const target = match[1];
      if (target.startsWith("./")) continue;
      findings.push({ rule: "unpinned_workflow_action", path: rel });
    }
  });
  return findings;
}

const baseline = loadBaseline();
const findings = args.has("--workflows") ? collectWorkflowFindings() : collectContentFindings();
const newFindings = findings.filter((finding) => !baseline.has(`${finding.rule}\t${finding.path}`));

if (newFindings.length > 0) {
  for (const finding of newFindings) {
    console.error(`${finding.path}: ${finding.rule}`);
  }
  console.error(`new findings: ${newFindings.length}; baseline findings: ${findings.length - newFindings.length}`);
  process.exit(1);
}

console.log(`docs policy passed; baseline findings: ${findings.length}; new findings: 0`);

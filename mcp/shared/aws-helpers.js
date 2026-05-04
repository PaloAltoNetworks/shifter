// Shared AWS-CLI argv-array helpers used by every Shifter MCP server.
//
// ADR-010 forbids shell-string interpolation into `child_process.exec*`.
// All `aws` invocations across `mcp/*` packages run through the
// helpers in this file. Callers MUST pass `args` as an argv array;
// shell strings throw `TypeError` before any process is spawned, so a
// stray callsite cannot silently re-introduce the command-injection
// path that issues #759 and #763 closed.
//
// Shape of the contract:
// - argv-array enforcement: `buildAwsArgv` rejects non-array `args`.
// - spawn-only execution: `awsExec` runs `aws` via `spawnSync`; no
//   `shell: true`.
// - `awsJson` appends `--output json` LAST so it overrides any
//   caller-supplied `--output` flag.
// - `awsText` returns trimmed stdout and never auto-appends
//   `--output text`; the caller decides.
// - `buildSsmSendCommandArgs` wraps the SSM `commands` payload in a
//   single argv element via `JSON.stringify`.
// - On failure, `awsExec` throws `Error("aws <service> <op>: <stderr>")`
//   so MCP handlers (which surface `err.message` directly to users)
//   can localize which AWS call failed.
//
// This module lives at `mcp/shared/` and is imported via relative
// path from each MCP server's lib.js. Each MCP server is its own npm
// package with its own `node_modules`; the shared module uses only
// `node:`-prefixed built-ins, so no cross-package npm dependency is
// needed.

import { spawnSync } from "node:child_process";

export const REGION = "us-east-2";

export function getProfile(profiles, env) {
  const profile = profiles[env];
  if (!profile) {
    throw new Error(
      `AWS profile not set for ${env}. Export PANW_SHIFTER_${env.toUpperCase()}_PROFILE`
    );
  }
  return profile;
}

export function buildAwsArgv(args, profile, region, extraFlags = []) {
  if (!Array.isArray(args)) {
    throw new TypeError(
      "AWS CLI args must be an argv array, not a shell string. " +
        "Passing a shell string would re-introduce the command-injection " +
        "path that issues #759 and #763 closed."
    );
  }
  return [
    ...args,
    "--profile",
    profile,
    "--region",
    region,
    ...extraFlags,
  ];
}

function defaultRunner(cmd, argv, options) {
  return spawnSync(cmd, argv, options);
}

function operationLabel(args) {
  if (!Array.isArray(args) || args.length === 0) return "aws";
  const verb = args.slice(0, 2).filter((v) => typeof v === "string" && !v.startsWith("-"));
  return verb.length > 0 ? `aws ${verb.join(" ")}` : "aws";
}

export function awsExec(profile, args, options = {}) {
  const {
    extraFlags = [],
    region = REGION,
    runner = defaultRunner,
    timeoutMs = 60000,
  } = options;
  const argv = buildAwsArgv(args, profile, region, extraFlags);
  const label = operationLabel(args);
  const result = runner("aws", argv, {
    encoding: "utf-8",
    timeout: timeoutMs,
  });
  if (result.error) {
    const wrapped = new Error(`${label}: ${result.error.message}`);
    wrapped.cause = result.error;
    throw wrapped;
  }
  if (result.status !== 0) {
    const stderr = (result.stderr || "").trim();
    const detail = stderr || `exited with status ${result.status}`;
    throw new Error(`${label}: ${detail}`);
  }
  return result.stdout;
}

export function awsJson(profile, args, options = {}) {
  const extraFlags = [
    ...(options.extraFlags || []),
    "--output",
    "json",
  ];
  const stdout = awsExec(profile, args, { ...options, extraFlags });
  return JSON.parse(stdout);
}

export function awsText(profile, args, options = {}) {
  return awsExec(profile, args, options).trim();
}

export function buildSsmSendCommandArgs({ instanceId, docName, commands }) {
  const params = JSON.stringify({ commands });
  return [
    "ssm",
    "send-command",
    "--instance-ids",
    instanceId,
    "--document-name",
    docName,
    "--parameters",
    params,
  ];
}

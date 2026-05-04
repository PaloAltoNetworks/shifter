// Testable logic extracted from index.js.
//
// Two boundaries must stay shell-free in this server (issue #759):
//
//   1. Local host shell: every aws-cli invocation goes through the
//      argv-array helpers below (`buildAwsArgv`, `awsExec`, `awsJson`,
//      `awsText`, `buildSsmSendCommandArgs`). Callers MUST pass argv
//      arrays. Shell strings are rejected with TypeError.
//
//   2. Remote portal shell: when an SSM `AWS-RunShellScript` payload
//      forwards a PAN-OS command to the NGFW via SSH, the user-supplied
//      command is base64-encoded by `buildNgfwSshCommands` so the
//      portal shell never evaluates the raw bytes. The portal decodes
//      the base64 and pipes the result into `ssh`'s stdin.
//
// These helpers mirror the ones in `mcp/ops/lib.js` (issue #763).
// Each MCP server is its own npm package, so the helpers are kept as
// a local copy here rather than pulled in across packages. See
// `SECURITY.md` for the rule that the two copies stay aligned.

import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";

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

// --- AWS CLI execution ----------------------------------------------------
//
// Every aws-cli invocation in this MCP server runs through these
// helpers. `buildAwsArgv` enforces the argv-array contract via
// TypeError so a stray shell string cannot silently re-introduce the
// command-injection path that issue #759 closes.

export function buildAwsArgv(args, profile, region, extraFlags = []) {
  if (!Array.isArray(args)) {
    throw new TypeError(
      "AWS CLI args must be an argv array, not a shell string. " +
        "Passing a shell string would re-introduce the command-injection " +
        "path that issue #759 closed."
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

// Builds an `aws <service> <op>: ...` operation label from the argv,
// or falls back to a generic "aws" prefix. The label is included in
// thrown errors so MCP handlers (which surface `err.message` directly
// to users) can localize which AWS call failed.
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

// --- SSM argv builder -----------------------------------------------------

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

// --- NGFW remote-shell payload --------------------------------------------
//
// `buildNgfwSshCommands` produces the SSM shell-command list that runs
// on the portal jump host. The PAN-OS `command` argument is
// base64-encoded into a single argv-safe token; the portal pipeline
// decodes it and feeds the bytes into `ssh`'s stdin. The portal shell
// therefore never evaluates the raw command, so payloads containing
// `$()`, backticks, single or double quotes, semicolons, ampersands,
// pipes, spaces, newlines, or even the heredoc terminator round-trip
// to PAN-OS verbatim. The SSH key still rides via a single-quoted
// heredoc (`'EOFKEY'`), which suppresses expansion of any `$`/`` ` ``
// characters that might appear inside a key.

const IPV4_OCTET = /^(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$/;

export function validateNgfwIp(ngfwIp) {
  if (typeof ngfwIp !== "string") {
    throw new TypeError("ngfwIp must be a string");
  }
  const parts = ngfwIp.split(".");
  if (parts.length !== 4 || !parts.every((p) => IPV4_OCTET.test(p))) {
    throw new Error(`Invalid NGFW IPv4 address: ${ngfwIp}`);
  }
  return ngfwIp;
}

// PAN-OS CLI is line-oriented: the appliance reads a command from SSH
// stdin and executes it when it sees a newline. The original
// `echo "${cmd}" | ssh ...` pipeline always appended a trailing
// newline. The base64 transport must preserve that semantic, so the
// helper appends `\n` to the command bytes before encoding (only
// when the caller's command does not already end in one). Without
// this, `show system info` and friends can hang or no-op depending
// on how the appliance handles EOF before Enter.
function ensureTrailingNewline(s) {
  return s.endsWith("\n") ? s : s + "\n";
}

export function buildNgfwSshCommands({ sshKey, ngfwIp, command, keyPath }) {
  if (typeof sshKey !== "string" || sshKey.length === 0) {
    throw new TypeError("sshKey must be a non-empty string");
  }
  if (typeof command !== "string") {
    throw new TypeError("command must be a string");
  }
  validateNgfwIp(ngfwIp);

  // Per-invocation key path keeps concurrent MCP calls from clobbering
  // each other's `/tmp/ngfw.pem`. The default uses a UUID, which is
  // shell-safe ([0-9a-f-]) so direct interpolation is fine. A
  // caller-supplied keyPath is validated to the same character set so
  // a future caller cannot widen the boundary inadvertently.
  const path = keyPath ?? `/tmp/ngfw-${randomUUID()}.pem`;
  if (!/^\/tmp\/ngfw-[A-Za-z0-9._-]+\.pem$/.test(path)) {
    throw new Error(`Invalid keyPath: ${path}`);
  }

  const encoded = Buffer.from(
    ensureTrailingNewline(command),
    "utf-8"
  ).toString("base64");

  // The script exit code must reflect the SSH/PAN-OS exit code so SSM
  // reports failed PAN-OS calls as failed. With a naive
  // `... ; rm -f ...` ordering, the rm would always run last (exit 0)
  // and mask the SSH failure. `set -e` plus an EXIT trap that captures
  // `$?` before cleanup propagates the real exit code to SSM.
  return [
    `set -e`,
    `cat > ${path} << 'EOFKEY'`,
    sshKey,
    `EOFKEY`,
    `chmod 600 ${path}`,
    `trap 'rc=$?; rm -f ${path}; exit $rc' EXIT`,
    `printf %s '${encoded}' | base64 -d | ssh -i ${path} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 admin@${ngfwIp} 2>&1`,
  ];
}

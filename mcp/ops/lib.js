// Shared constants and helpers for the shifter-ops MCP server.

import { spawnSync } from "node:child_process";

export const REGION = "us-east-2";

// --- AWS ---

export const LOG_GROUPS = {
  portal: { dev: "/portal/dev-portal", prod: "/portal/prod-portal" },
  provisioner: {
    dev: "/ecs/dev-portal-pulumi-provisioner",
    prod: "/ecs/prod-portal-pulumi-provisioner",
  },
  "guacamole-client": {
    dev: "/ecs/dev-portal-guacamole-client",
    prod: "/ecs/prod-portal-guacamole-client",
  },
  guacd: { dev: "/ecs/dev-portal-guacd", prod: "/ecs/prod-portal-guacd" },
  "network-firewall": {
    dev: "/aws/network-firewall/dev-range",
    prod: "/aws/network-firewall/prod-range",
  },
  rds: {
    dev: "/aws/rds/instance/dev-portal-db/postgresql",
    prod: "/aws/rds/instance/prod-portal-db/postgresql",
  },
};

/**
 * Resolve a component shorthand (e.g. "provisioner") to its CloudWatch
 * log group name, or return the input as-is if it's already a log group path.
 */
export function resolveLogGroup(componentOrPath, env) {
  const entry = LOG_GROUPS[componentOrPath];
  if (entry) {
    return entry[env];
  }
  return componentOrPath;
}

/**
 * Build EC2 describe-instances filters array.
 */
export function buildInstanceFilters({ name_filter, include_terminated } = {}) {
  const filters = [];
  if (name_filter) {
    filters.push({ Name: "tag:Name", Values: [name_filter] });
  }
  const states = ["pending", "running", "stopping", "stopped"];
  if (include_terminated) {
    states.push("shutting-down", "terminated");
  }
  filters.push({ Name: "instance-state-name", Values: states });
  return filters;
}

// --- Database ---

export const LOCAL_PORTS = { dev: 15432, prod: 15433 };

export const SERVICE_LAYERS = {
  cms_: "Shifter CMS (content management)",
  engine_: "Shifter Engine (range provisioning)",
  risk_register_: "Risk Register (security tracking)",
  auth_: "Django Auth",
  django_: "Django Framework",
  health_check_: "Health Checks",
};

// Legacy mission_control_ tables were moved to other apps but kept their db_table names
export const LEGACY_TABLE_MAP = {
  mission_control_range: "Shifter Engine (range provisioning)",
  mission_control_userprofile: "Shifter Admin (management)",
  mission_control_activitylog: "Shifter Admin (management)",
};

export function getServiceLayer(tableName) {
  if (LEGACY_TABLE_MAP[tableName]) return LEGACY_TABLE_MAP[tableName];
  for (const [prefix, layer] of Object.entries(SERVICE_LAYERS)) {
    if (tableName.startsWith(prefix)) return layer;
  }
  return "Unknown";
}

export const FORBIDDEN_PATTERN =
  /\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|VACUUM|REINDEX)\b/i;

// --- Risk Register Constants ---

export const RISK_TABLES = {
  risk: "risk_register_risk",
  comment: "risk_register_comment",
  apikey: "risk_register_apikey",
  audit_log: "risk_register_auditlog",
};

export const SEVERITY_VALUES = ["critical", "high", "medium", "low"];
export const STATUS_VALUES = [
  "open",
  "acknowledged",
  "mitigating",
  "resolved",
  "closed",
];
export const STRIDE_CODES = ["S", "T", "R", "I", "D", "E"];
export const STRIDE_LABELS = {
  S: "Spoofing",
  T: "Tampering",
  R: "Repudiation",
  I: "Information Disclosure",
  D: "Denial of Service",
  E: "Elevation of Privilege",
};

/**
 * Build a parameterized UPDATE SET clause from field:value pairs.
 * Skips entries where value is undefined.
 * @param {Object} fields - { column_name: value } pairs
 * @param {number} startParam - Starting $N parameter index
 * @returns {{ setClause: string, values: any[], nextParam: number }}
 */
export function buildUpdateSet(fields, startParam = 1) {
  const entries = Object.entries(fields).filter(([, v]) => v !== undefined);
  if (entries.length === 0) {
    throw new Error("No fields to update");
  }
  const setParts = [];
  const values = [];
  let paramIdx = startParam;
  for (const [field, value] of entries) {
    setParts.push(`${field} = $${paramIdx}`);
    values.push(value);
    paramIdx++;
  }
  return { setClause: setParts.join(", "), values, nextParam: paramIdx };
}

// --- SSM ---

/**
 * Map EC2 PlatformDetails to the correct SSM document name.
 * PlatformDetails values: "Linux/UNIX", "Windows", "Windows with SQL Server", etc.
 */
export function getSsmDocument(platformDetails) {
  if (platformDetails && platformDetails.toLowerCase().startsWith("windows")) {
    return "AWS-RunPowerShellScript";
  }
  return "AWS-RunShellScript";
}

// --- S3 ---

export const MAX_S3_READ_SIZE = 1024 * 1024; // 1MB

const BINARY_PREFIXES = ["image/", "video/", "audio/"];
const BINARY_TYPES = new Set([
  "application/octet-stream",
  "application/zip",
  "application/gzip",
]);

export function isBinaryContentType(contentType) {
  if (!contentType) return false;
  if (BINARY_TYPES.has(contentType)) return true;
  return BINARY_PREFIXES.some((p) => contentType.startsWith(p));
}

// --- Django Management ---

const ALLOWED_MANAGE_COMMANDS = new Set([
  "check",
  "showmigrations",
  "diffsettings",
  "inspectdb",
  "dbshell",
  "clearsessions",
  "collectstatic",
  "show_urls",
]);

const BLOCKED_MANAGE_COMMANDS = new Set([
  "flush",
  "sqlflush",
  "reset_db",
  "migrate",
  "createsuperuser",
  "changepassword",
  "loaddata",
  "dumpdata",
  "shell",
  "shell_plus",
  "runserver",
  "test",
]);

export function validateManageCommand(command) {
  const parts = command.trim().split(/\s+/);
  const baseCmd = parts[0];
  if (BLOCKED_MANAGE_COMMANDS.has(baseCmd)) {
    throw new Error(`Blocked management command: ${baseCmd}`);
  }
  if (!ALLOWED_MANAGE_COMMANDS.has(baseCmd)) {
    throw new Error(
      `Unknown management command: ${baseCmd}. Allowed: ${[...ALLOWED_MANAGE_COMMANDS].join(", ")}`,
    );
  }
  return parts;
}

// --- AWS CLI execution ---
//
// All aws-cli invocations run through these helpers. Callers MUST pass
// args as an argv array, not a shell string — buildAwsArgv enforces it
// via TypeError. The argv is handed to spawnSync, so values containing
// `$()`, backticks, quotes, etc. are forwarded literally to the aws
// binary instead of being interpreted by the local host shell. Shell
// escaping is not a remediation strategy for this component; see
// mcp/ops/SECURITY.md.

/**
 * Build the argv array passed to spawnSync("aws", ...).
 * Preserves caller args byte-for-byte and appends profile, region, and
 * any extra flags last so the helper's flags override anything the
 * caller supplied (matches the prior shell-string ordering).
 */
export function buildAwsArgv(args, profile, region, extraFlags = []) {
  if (!Array.isArray(args)) {
    throw new TypeError(
      "AWS CLI args must be an argv array, not a shell string. " +
        "Passing a shell string would re-introduce the command-injection " +
        "path that issue #763 closed."
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

/**
 * Run `aws` with an argv array. Returns stdout. Throws on non-zero exit
 * with the trimmed stderr (or a generic message). The runner is
 * injectable so tests can capture the argv without spawning a real
 * process.
 */
export function awsExec(profile, args, options = {}) {
  const {
    extraFlags = [],
    region = REGION,
    runner = defaultRunner,
    timeoutMs = 60000,
  } = options;
  const argv = buildAwsArgv(args, profile, region, extraFlags);
  const result = runner("aws", argv, {
    encoding: "utf-8",
    timeout: timeoutMs,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const stderr = (result.stderr || "").trim();
    throw new Error(
      stderr || `aws exited with status ${result.status}`
    );
  }
  return result.stdout;
}

/**
 * Run `aws` with `--output json` appended and parse the result.
 * `--output json` is the LAST flag in the final argv so it always
 * overrides any `--output` flag the caller supplied via either `args`
 * or `options.extraFlags` (matches the prior shell-string behavior of
 * `aws()`, where `--output json` was tacked on at the end).
 */
export function awsJson(profile, args, options = {}) {
  const extraFlags = [
    ...(options.extraFlags || []),
    "--output",
    "json",
  ];
  const stdout = awsExec(profile, args, { ...options, extraFlags });
  return JSON.parse(stdout);
}

/**
 * Run `aws` and return trimmed stdout. Does NOT append `--output text`;
 * callers that need text output must include it in their args.
 */
export function awsText(profile, args, options = {}) {
  return awsExec(profile, args, options).trim();
}

// --- Per-tool argv builders for the named-vulnerable paths in #763 ---
//
// These exist as pure functions so tests can assert that
// user-controlled values land as literal argv elements without ever
// spawning aws. The handlers in index.js call these and pass the
// result straight to aws()/awsText(). Adding a new
// metacharacter-containing payload to a regression test means
// extending the per-tool test cases in lib.test.js, not editing
// index.js.

/**
 * CloudWatch `logs filter-log-events` argv. The user-supplied
 * `filterPattern` becomes a single argv element; no JSON.stringify
 * wrapping is needed because there is no shell to interpret it.
 */
export function buildFilterLogEventsArgs({ logGroup, filterPattern, limit }) {
  return [
    "logs",
    "filter-log-events",
    "--log-group-name",
    logGroup,
    "--filter-pattern",
    filterPattern,
    "--limit",
    String(limit),
  ];
}

/**
 * SSM `send-command` argv. The `commands` payload is JSON.stringify'd
 * into a single `--parameters` argv element. The aws CLI parses that
 * JSON itself; the local shell never sees it.
 */
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

/**
 * SSM `send-command` argv for the Django manage.py wrapper. The user's
 * `command` is concatenated into the docker-exec invocation that runs
 * inside the remote shell on the EC2 host. That remote shell IS
 * intentional (the tool's contract is to forward a command for remote
 * execution); the security boundary protected here is the LOCAL host
 * shell, which never sees the payload because the wrapped string
 * lands inside the JSON parameters argv element.
 */
export function buildRunManageArgs({ targetId, command }) {
  const dockerCmd = `docker exec portal python manage.py ${command}`;
  return buildSsmSendCommandArgs({
    instanceId: targetId,
    docName: "AWS-RunShellScript",
    commands: [dockerCmd],
  });
}

// --- Shared ---

export function getProfile(profiles, env) {
  const profile = profiles[env];
  if (!profile) {
    throw new Error(
      `AWS profile not set for ${env}. Export PANW_SHIFTER_${env.toUpperCase()}_PROFILE`
    );
  }
  return profile;
}

// Shared constants and helpers for the shifter-ops MCP server.
//
// AWS-CLI argv-array helpers (`buildAwsArgv`, `awsExec`, `awsJson`,
// `awsText`, `buildSsmSendCommandArgs`, plus `REGION` and
// `getProfile`) live in `mcp/shared/aws-helpers.js` and are
// re-exported here so existing call sites in this package — and the
// per-tool argv builders below — keep working unchanged. The shared
// module governs the argv-array contract that ADR-010 enforces;
// see `mcp/ngfw/lib.js` and `mcp/ops/SECURITY.md` for context.

import { buildSsmSendCommandArgs } from "../shared/aws-helpers.js";

export {
  REGION,
  getProfile,
  buildAwsArgv,
  awsExec,
  awsJson,
  awsText,
  buildSsmSendCommandArgs,
} from "../shared/aws-helpers.js";

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

/**
 * Build the `pg.Pool` config for the env-scoped Postgres connection that
 * tunnels through SSM. Issue #1190 — TLS verification was previously
 * disabled (`rejectUnauthorized: false`) to work around the cert/host
 * mismatch caused by tunneling: the cert presented by RDS carries the
 * RDS endpoint in its CN/SAN, but the local node-postgres client
 * connects to `localhost`. The fix preserves verification by setting
 * `servername` on the TLS options to the captured `rdsHost`; Node's
 * `tls.connect` then performs SNI and hostname verification against
 * the real RDS endpoint instead of `localhost`, while the TCP stream
 * still rides the local SSM port forward.
 *
 * The function fails closed: callers must pass a non-empty `rdsHost`
 * captured at tunnel-start time. Reintroducing `rejectUnauthorized:
 * false` requires editing this single helper; the
 * `mcp-ops-tls-strict` adr_guard check backstops accidental
 * regression in any other `mcp/ops/*.js` file.
 *
 * RDS Postgres servers send the full intermediate chain rooted at
 * Amazon Root CA 1, which is present in every mainstream OS root
 * store, so Node's default trust store verifies the chain without a
 * bundled CA. See `mcp/ops/SECURITY.md` § "Database TLS" for the trust
 * model and the procedure to switch to a pinned `ca:` bundle if the
 * default trust store ever proves insufficient.
 */
export function buildPoolConfig({ rdsHost, creds, port }) {
  if (typeof rdsHost !== "string" || rdsHost.trim() === "") {
    throw new TypeError(
      "buildPoolConfig: rdsHost is required (captured at tunnel-start time)",
    );
  }
  if (!creds || typeof creds !== "object") {
    throw new TypeError("buildPoolConfig: creds is required");
  }
  if (typeof port !== "number" || !Number.isInteger(port) || port <= 0) {
    throw new TypeError("buildPoolConfig: port must be a positive integer");
  }
  return {
    host: "localhost",
    port,
    user: creds.username,
    password: creds.password,
    database: creds.dbname,
    ssl: {
      rejectUnauthorized: true,
      // SNI + hostname check fire against the real RDS endpoint, not
      // the localhost target of the SSM port forward.
      servername: rdsHost,
    },
    max: 3,
    connectionTimeoutMillis: 10000,
    idleTimeoutMillis: 30000,
  };
}

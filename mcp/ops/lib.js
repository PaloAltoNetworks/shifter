// Shared constants and helpers for the shifter-ops MCP server.
//
// AWS-CLI argv-array helpers (`buildAwsArgv`, `awsExec`, `awsJson`,
// `awsText`, `buildSsmSendCommandArgs`, plus `REGION` and
// `getProfile`) live in `mcp/shared/aws-helpers.js` and are
// re-exported here so existing call sites in this package — and the
// per-tool argv builders below — keep working unchanged. The shared
// module governs the argv-array contract that ADR-010 enforces;
// see `mcp/ngfw/lib.js` and `mcp/ops/SECURITY.md` for context.

import { spawnSync } from "node:child_process";
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

// --- GitHub Actions (gh CLI) ---

export const DEFAULT_GITHUB_REPO = "Brad-Edwards/shifter";

/** Protected integration branch for prod AMI promotion workflows. */
export const PROMOTE_AMI_REF = "dev";

export const BASE_AMI_TYPES = Object.freeze([
  "kali",
  "ubuntu",
  "windows",
  "dc",
  "brokenbk",
]);

/** Protected integration branch for prod GCE image promotion workflows. */
export const PROMOTE_GCE_IMAGE_REF = "dev";

// GCE image build/promote (issue #505, PLAT-001.10). Mirrors the AWS AMI
// constants above for the GCP guest-image bake pipeline. The order matches the
// `image_type` choices in .github/workflows/packer-gcp.yml.
export const GCE_IMAGE_TYPES = Object.freeze([
  "ubuntu",
  "brokenbk",
  "kali",
  "windows",
  "dc",
]);

/**
 * Build argv for `gh workflow run`. User-controlled values land as
 * literal argv elements; no shell interpolation (ADR-010).
 */
export function buildGhWorkflowRunArgs({ workflow, repo, ref, inputs = {} }) {
  if (typeof workflow !== "string" || workflow.trim() === "") {
    throw new TypeError("buildGhWorkflowRunArgs: workflow is required");
  }
  if (typeof repo !== "string" || repo.trim() === "") {
    throw new TypeError("buildGhWorkflowRunArgs: repo is required");
  }
  if (typeof ref !== "string" || ref.trim() === "") {
    throw new TypeError("buildGhWorkflowRunArgs: ref is required");
  }
  if (inputs === null || typeof inputs !== "object" || Array.isArray(inputs)) {
    throw new TypeError("buildGhWorkflowRunArgs: inputs must be an object");
  }
  const args = ["workflow", "run", workflow, "--repo", repo, "--ref", ref];
  for (const [key, value] of Object.entries(inputs)) {
    args.push("-f", `${key}=${String(value)}`);
  }
  return args;
}

export function resolveGhToken(env = process.env) {
  const token = env.GH_TOKEN || env.GITHUB_TOKEN;
  if (typeof token !== "string" || token.trim() === "") {
    throw new Error(
      "GitHub token not configured. Set GH_TOKEN or GITHUB_TOKEN in the MCP environment.",
    );
  }
  return token.trim();
}

function ghOperationLabel(args) {
  if (!Array.isArray(args) || args.length < 2) return "gh";
  return `gh ${args.slice(0, 2).join(" ")}`;
}

function defaultGhRunner(argv, options) {
  return spawnSync("gh", argv, options); // NOSONAR
}

export function ghExec(args, options = {}) {
  if (!Array.isArray(args)) {
    throw new TypeError(
      "gh CLI args must be an argv array, not a shell string.",
    );
  }
  const {
    env = process.env,
    runner = defaultGhRunner,
    timeoutMs = 60000,
    token,
  } = options;
  const ghToken = token ?? resolveGhToken(env);
  const label = ghOperationLabel(args);
  const result = runner(args, {
    encoding: "utf-8",
    timeout: timeoutMs,
    env: { ...env, GH_TOKEN: ghToken, GITHUB_TOKEN: ghToken },
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
  return (result.stdout || "").trim();
}

function defaultGitRunner(argv, options) {
  return spawnSync("git", argv, options); // NOSONAR
}

/**
 * Resolve the current git branch for workflow `--ref`, mirroring
 * `scripts/ami.sh`. Falls back to `defaultRef` when git is unavailable.
 */
export function resolveGitRef(cwd, options = {}) {
  const { runner = defaultGitRunner, defaultRef = "dev" } = options;
  const result = runner(["rev-parse", "--abbrev-ref", "HEAD"], {
    cwd,
    encoding: "utf-8",
    timeout: 5000,
  });
  if (result.error || result.status !== 0) {
    return defaultRef;
  }
  const ref = (result.stdout || "").trim();
  if (!ref || ref === "HEAD") {
    return defaultRef;
  }
  return ref;
}

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

// A single validated management-command token: the base command or one
// argument. Positive allowlist — any token containing shell-control syntax
// (`;`, `|`, `&`, `$`, backtick, `<`, `>`, `(`, `)`, quotes, `*`, `#`,
// whitespace, CR/LF, ...) fails to match and is rejected. Optional leading
// dashes support flags (`--deploy`, `-v2`) and `=` supports `--flag=value`.
// The supported language is "Django management command argv", not a shell
// grammar — see docs/architecture/mcp-ops-manage-command-ssm-boundary-preflight-1176.md.
const SAFE_MANAGE_TOKEN = /^-{0,2}[A-Za-z0-9][A-Za-z0-9._=-]*$/;

// Thrown when a management command carries shell-control syntax. Deliberately
// generic: the attacker-controlled payload is never echoed into the error
// message, MCP response, audit record, or test diagnostics (issue #1176).
const SHELL_SYNTAX_ERROR =
  "Management command contains disallowed characters or shell syntax";

// Validate that every token is a safe management-command token. The base
// allowlist below only governs the first token; validating every token here
// is what prevents user-controlled arguments from reaching the remote shell
// verbatim (issue #1176 / CWE-78).
function assertSafeManageTokens(parts) {
  for (const part of parts) {
    if (typeof part !== "string" || !SAFE_MANAGE_TOKEN.test(part)) {
      throw new Error(SHELL_SYNTAX_ERROR);
    }
  }
}

export function validateManageCommand(command) {
  const trimmed = typeof command === "string" ? command.trim() : "";
  if (trimmed === "") {
    throw new Error("Empty management command");
  }
  const parts = trimmed.split(/\s+/);
  // Reject shell-control syntax in ANY token before trusting the base
  // command, so a rejected payload never reaches the allowlist error (which
  // echoes the base command) or the SSM argv builder.
  assertSafeManageTokens(parts);
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
 * SSM `send-command` argv for the Django manage.py wrapper.
 *
 * `commandParts` MUST be the validated argv returned by
 * `validateManageCommand` — a structured array of shell-metacharacter-free
 * tokens, NOT a raw command string. The remote `AWS-RunShellScript` shell
 * on the EC2 host executes the rendered command, so the security boundary
 * protected here is the REMOTE shell: the fixed `docker exec portal python
 * manage.py …` wrapper is joined only from validated tokens, leaving no
 * user-controlled separators, substitutions, redirects, pipes, or newlines
 * for that shell to interpret (issue #1176 / CWE-78). Local argv safety
 * (buildSsmSendCommandArgs keeping the payload in one JSON element) is
 * necessary but not sufficient once the payload reaches the remote shell.
 *
 * The per-token check is repeated here as defense in depth so the renderer
 * is safe regardless of how a caller obtained `commandParts`.
 */
export function buildRunManageArgs({ targetId, commandParts }) {
  if (!Array.isArray(commandParts) || commandParts.length === 0) {
    throw new Error("Empty management command");
  }
  assertSafeManageTokens(commandParts);
  const dockerCmd = `docker exec portal python manage.py ${commandParts.join(" ")}`;
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

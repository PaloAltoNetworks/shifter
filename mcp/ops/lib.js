// Shared constants and helpers for the shifter-ops MCP server.

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

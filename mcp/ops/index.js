#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { spawn } from "child_process";
import pg from "pg";
import net from "net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  REGION,
  LOCAL_PORTS,
  getServiceLayer,
  getProfile as _getProfile,
  FORBIDDEN_PATTERN,
  resolveLogGroup,
  buildInstanceFilters,
  RISK_TABLES,
  buildUpdateSet,
  getSsmDocument,
  MAX_S3_READ_SIZE,
  isBinaryContentType,
  validateManageCommand,
  awsJson,
  awsText as awsTextLib,
  buildAwsArgv,
  buildFilterLogEventsArgs,
  buildSsmSendCommandArgs,
  buildRunManageArgs,
  buildPoolConfig,
} from "./lib.js";
import {
  loadPolicy,
  profileFromEnv,
  registerTool,
  consumeApexToken,
  validateApexCoverage,
} from "./policy.js";

// Spawn a long-running aws-cli process (e.g. an SSM port-forward that
// must stay open). Uses the same argv-array discipline as the
// shared aws()/awsText() helpers so tunnel call sites cannot
// accidentally re-introduce shell-string interpolation.
function spawnAws(profile, args, options = {}) {
  const argv = buildAwsArgv(args, profile, REGION);
  return spawn("aws", argv, options);
}

const { Pool } = pg;

const PROFILES = {
  dev: process.env.PANW_SHIFTER_DEV_PROFILE,
  prod: process.env.PANW_SHIFTER_PROD_PROFILE,
};

function getProfile(env) {
  return _getProfile(PROFILES, env);
}

// ==========================================================================
// AWS helpers
//
// All aws-cli invocations go through these wrappers, which delegate to
// the argv-array helpers in lib.js. Callers MUST pass `args` as an
// array of argv elements — never as a shell string. The lib helpers
// throw TypeError if a string slips through.
// ==========================================================================

function aws(profile, args) {
  return awsJson(profile, args);
}

function awsText(profile, args) {
  return awsTextLib(profile, args);
}

function getInstancePlatform(profile, instanceId) {
  // `--output text` so the scalar query result is returned as the raw
  // string (`Linux/UNIX`, `Windows`) rather than JSON-quoted
  // (`"Linux/UNIX"`). Without this getSsmDocument() never matches
  // "windows" because the value starts with a `"` instead of `w`.
  return awsText(profile, [
    "ec2",
    "describe-instances",
    "--instance-ids",
    instanceId,
    "--query",
    "Reservations[0].Instances[0].PlatformDetails",
    "--output",
    "text",
  ]);
}

function ok(text) {
  return { content: [{ type: "text", text }] };
}

function err(e) {
  return {
    content: [{ type: "text", text: `Error: ${e.message}` }],
    isError: true,
  };
}

// ==========================================================================
// Database tunnel & pool management
// ==========================================================================

const tunnels = {}; // env -> { process }
const credentials = {}; // env -> { username, password, dbname }
const pools = {}; // env -> pg.Pool
const portalTunnels = {}; // env -> { process, port }

async function isPortOpen(port) {
  return new Promise((resolve) => {
    const sock = new net.Socket();
    sock.setTimeout(1000);
    sock.on("connect", () => {
      sock.destroy();
      resolve(true);
    });
    sock.on("error", () => resolve(false));
    sock.on("timeout", () => {
      sock.destroy();
      resolve(false);
    });
    sock.connect(port, "127.0.0.1");
  });
}

async function fetchCredentials(env) {
  if (credentials[env]) return credentials[env];

  const profile = getProfile(env);
  const secretId = `shifter-${env}-portal-db-credentials`;

  const result = awsTextLib(
    profile,
    [
      "secretsmanager",
      "get-secret-value",
      "--secret-id",
      secretId,
      "--query",
      "SecretString",
      "--output",
      "text",
    ],
    { timeoutMs: 30000 }
  );

  credentials[env] = JSON.parse(result);
  return credentials[env];
}

function killTunnel(env) {
  if (tunnels[env]?.process) {
    tunnels[env].process.kill();
    delete tunnels[env];
  }
}

function discoverRdsEndpoint(env) {
  // The RDS endpoint is the verification target for TLS (#1190) and
  // the destination address for the SSM port-forward. Both code
  // paths in ensureTunnel() rely on this — the "tunnel already open"
  // shortcut needs the endpoint too, not just the start-from-scratch
  // path. Factored out so the lookup runs every invocation and we
  // never reach getPool() with `tunnels[env].rdsHost === undefined`
  // (codex review #1180 cycle 1 finding 2).
  const profile = getProfile(env);
  const jmesQuery = `DBInstances[?DBInstanceIdentifier==\`${env}-portal-db\`].Endpoint.Address`;
  const rdsHost = awsTextLib(
    profile,
    [
      "rds",
      "describe-db-instances",
      "--query",
      jmesQuery,
      "--output",
      "text",
    ],
    { timeoutMs: 30000 }
  );
  if (!rdsHost || rdsHost === "None") {
    throw new Error(`Could not find RDS endpoint for ${env}`);
  }
  return rdsHost;
}

async function ensureTunnel(env) {
  const port = LOCAL_PORTS[env];

  // Tunnel-already-up paths: still resolve and cache the RDS
  // endpoint so getPool()'s buildPoolConfig() has the verification
  // target. Without this, a pre-existing port-forward (started by a
  // previous server instance, an operator's manual session, etc.)
  // would short-circuit ensureTunnel() and leave rdsHost undefined,
  // which buildPoolConfig() refuses by design.
  if (tunnels[env]?.process && !tunnels[env].process.killed) {
    if (await isPortOpen(port)) {
      if (!tunnels[env].rdsHost) {
        tunnels[env].rdsHost = discoverRdsEndpoint(env);
      }
      return;
    }
    killTunnel(env);
  }

  if (await isPortOpen(port)) {
    // Port is open but we don't own the tunnel record. Cache the
    // RDS endpoint so getPool can target the right cert; record the
    // tunnel as managed-elsewhere (no `.process`) so killTunnel
    // doesn't try to kill someone else's process.
    const rdsHost = discoverRdsEndpoint(env);
    tunnels[env] = { process: null, rdsHost };
    return;
  }

  const profile = getProfile(env);

  const instanceId = awsTextLib(
    profile,
    [
      "ec2",
      "describe-instances",
      "--filters",
      `Name=tag:Name,Values=${env}-portal-ec2`,
      "Name=instance-state-name,Values=running",
      "--query",
      "Reservations[0].Instances[0].InstanceId",
      "--output",
      "text",
    ],
    { timeoutMs: 30000 }
  );

  if (!instanceId || instanceId === "None") {
    throw new Error(`Could not find running ${env} portal EC2 instance`);
  }

  const rdsHost = discoverRdsEndpoint(env);

  const proc = spawnAws(
    profile,
    [
      "ssm",
      "start-session",
      "--target",
      instanceId,
      "--document-name",
      "AWS-StartPortForwardingSessionToRemoteHost",
      "--parameters",
      JSON.stringify({
        host: [rdsHost],
        portNumber: ["5432"],
        localPortNumber: [String(port)],
      }),
    ],
    { stdio: ["ignore", "pipe", "pipe"] }
  );

  // Capture the discovered rdsHost so getPool() can set ssl.servername
  // for cert verification. The tunnel terminates at localhost but the
  // RDS-issued cert names the RDS endpoint; without this the previous
  // `rejectUnauthorized: false` workaround silently broke TLS trust.
  tunnels[env] = { process: proc, rdsHost };

  proc.on("exit", () => {
    delete tunnels[env];
  });

  for (let i = 0; i < 30; i++) {
    if (await isPortOpen(port)) return;
    await new Promise((r) => setTimeout(r, 1000));
  }

  proc.kill();
  delete tunnels[env];
  throw new Error("Tunnel failed to start within 30 seconds");
}

async function getPool(env) {
  await ensureTunnel(env);
  const creds = await fetchCredentials(env);

  if (!pools[env]) {
    const rdsHost = tunnels[env]?.rdsHost;
    pools[env] = new Pool(
      buildPoolConfig({ rdsHost, creds, port: LOCAL_PORTS[env] }),
    );
    pools[env].on("error", () => {
      pools[env]?.end().catch(() => {});
      delete pools[env];
    });
  }

  return pools[env];
}

async function withClient(env, { readOnly = true } = {}, fn) {
  const pool = await getPool(env);
  const client = await pool.connect();
  try {
    if (readOnly) {
      await client.query("SET default_transaction_read_only = ON");
    }
    return await fn(client);
  } finally {
    if (readOnly) {
      await client
        .query("SET default_transaction_read_only = OFF")
        .catch(() => {});
    }
    client.release();
  }
}

// ==========================================================================
// Cleanup
// ==========================================================================

function cleanup() {
  for (const env of Object.keys(pools)) {
    pools[env]?.end().catch(() => {});
    delete pools[env];
  }
  for (const env of Object.keys(tunnels)) {
    if (tunnels[env]?.process) {
      tunnels[env].process.kill();
    }
  }
}

process.on("SIGTERM", () => {
  cleanup();
  process.exit(0);
});
process.on("SIGINT", () => {
  cleanup();
  process.exit(0);
});
process.on("exit", cleanup);

// ==========================================================================
// MCP Server
// ==========================================================================

const server = new McpServer({ name: "shifter-ops", version: "1.0.0" });

// Phase 5 (#1201): load .shifter.yaml at startup. The active profile
// is `SHIFTER_OPS_PROFILE` (read once here; runtime profile flips
// would be a confused-deputy surface). A missing or malformed
// `.shifter.yaml` throws and the server exits before any tool is
// registered — fail closed is the only correct path.
const _HERE = path.dirname(fileURLToPath(import.meta.url));
const _REPO_ROOT = path.resolve(_HERE, "..", "..");
const policy = loadPolicy({
  path: path.join(_REPO_ROOT, ".shifter.yaml"),
  profile: profileFromEnv(process.env),
});
const ctx = { server, policy };

// `approve` is the operator-confirmation MCP tool. The agent reads
// the token off the operator's terminal (which the server printed to
// stderr just before an apex operation parked) and calls this tool
// with it. Registered as `observability` so every profile sees it —
// without `approve`, no apex op can ever succeed and the server
// degrades to fail-closed-on-every-apex.
registerTool(ctx, {
  name: "approve",
  klass: "observability",
  // Codex review #1201 cycle 2: the apex token must NEVER appear in
  // audit records. `sensitive_args` instructs `_safeOutputArgs` to
  // redact it on the audit/plan-summary surfaces while the handler
  // still receives the raw value to consume the matching pending
  // apex.
  sensitive_args: ["token"],
  description:
    "Release a pending apex operator-confirmation token (printed to server stderr).",
  schema: {
    token: z
      .string()
      .regex(/^[a-f0-9]{32}$/i, "Must be a 32-char hex token from stderr")
      .describe("Apex confirmation token from stderr"),
  },
  handler: async ({ token }) => {
    const ok = consumeApexToken(token);
    return {
      content: [
        {
          type: "text",
          text: ok
            ? "Approved."
            : "Error: token unknown, already consumed, or expired.",
        },
      ],
      ...(ok ? {} : { isError: true }),
    };
  },
});

const EnvSchema = z
  .enum(["dev", "prod"])
  .default("dev")
  .describe("Environment (dev or prod). Defaults to dev.");

// Input validation patterns — defense in depth on top of argv-array AWS execution
const Ec2Id = z
  .string()
  .regex(/^i-[0-9a-f]{8,17}$/, "Must be a valid EC2 instance ID");
const SsmCommandId = z
  .string()
  .regex(
    /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i,
    "Must be a valid SSM command ID (UUID)"
  );
const SafePath = z
  .string()
  .regex(/^[\w\/.:\-\[\]#, ]+$/, "Contains invalid characters");
const SafeName = z.string().regex(/^[\w.*?-]+$/, "Contains invalid characters");
const SecretIdSchema = z
  .string()
  .regex(/^[\w/+=.@-]+$/, "Contains invalid characters");
const ArnSchema = z
  .string()
  .regex(/^arn:aws[\w:*\/.-]+$/, "Must be a valid ARN");

// ==========================================================================
// CloudWatch Logs
// ==========================================================================

registerTool(ctx, {
  name: "describe_log_streams",
  klass: "observability",
  description: "List recent log streams for a component or log group. Use component shorthand (portal, provisioner, guacamole-client, guacd, network-firewall, rds) or a full log group path.",
  schema: {
    env: EnvSchema,
    component: SafePath.describe(
      "Component shorthand (portal, provisioner, guacamole-client, guacd, network-firewall, rds) or full log group path"
    ),
    limit: z
      .number()
      .int()
      .min(1)
      .max(50)
      .default(5)
      .describe("Number of streams to return (default 5)"),
  },
  handler: async ({ env, component, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(profile, [
        "logs",
        "describe-log-streams",
        "--log-group-name",
        logGroup,
        "--order-by",
        "LastEventTime",
        "--descending",
        "--limit",
        String(limit),
      ]);
      const streams = result.logStreams.map((s) => ({
        name: s.logStreamName,
        lastEvent: s.lastEventTimestamp
          ? new Date(s.lastEventTimestamp).toISOString()
          : "never",
      }));
      return ok(JSON.stringify(streams, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "get_log_events",
  klass: "observability",
  untrusted_source: "logs",
  description: "Get log events from a specific log stream",
  schema: {
    env: EnvSchema,
    component: SafePath.describe("Component shorthand or full log group path"),
    stream_name: SafePath.describe("Log stream name"),
    limit: z
      .number()
      .int()
      .min(1)
      .max(200)
      .default(50)
      .describe("Number of events (default 50)"),
  },
  handler: async ({ env, component, stream_name, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(profile, [
        "logs",
        "get-log-events",
        "--log-group-name",
        logGroup,
        "--log-stream-name",
        stream_name,
        "--limit",
        String(limit),
      ]);
      const lines = result.events.map(
        (e) => `[${new Date(e.timestamp).toISOString()}] ${e.message}`
      );
      return ok(lines.join("\n"));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "filter_log_events",
  klass: "observability",
  untrusted_source: "logs",
  description: "Search log events across streams using a CloudWatch filter pattern",
  schema: {
    env: EnvSchema,
    component: SafePath.describe("Component shorthand or full log group path"),
    filter_pattern: z
      .string()
      .describe(
        'CloudWatch filter pattern (e.g. \'error\', \'"stack trace"\')'
      ),
    limit: z
      .number()
      .int()
      .min(1)
      .max(200)
      .default(50)
      .describe("Max events to return (default 50)"),
  },
  handler: async ({ env, component, filter_pattern, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(
        profile,
        buildFilterLogEventsArgs({
          logGroup,
          filterPattern: filter_pattern,
          limit,
        })
      );
      const lines = result.events.map(
        (e) =>
          `[${new Date(e.timestamp).toISOString()}] [${e.logStreamName}] ${e.message}`
      );
      return ok(
        lines.length > 0 ? lines.join("\n") : "No matching events found."
      );
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "tail_logs",
  klass: "observability",
  untrusted_source: "logs",
  description: "Tail recent logs for a component (shortcut for describe_streams + get_log_events on the latest stream)",
  schema: {
    env: EnvSchema,
    component: SafePath.describe("Component shorthand or full log group path"),
    limit: z
      .number()
      .int()
      .min(1)
      .max(200)
      .default(50)
      .describe("Number of events (default 50)"),
  },
  handler: async ({ env, component, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const streams = aws(profile, [
        "logs",
        "describe-log-streams",
        "--log-group-name",
        logGroup,
        "--order-by",
        "LastEventTime",
        "--descending",
        "--limit",
        "1",
      ]);
      if (!streams.logStreams || streams.logStreams.length === 0) {
        return ok("No log streams found.");
      }
      const streamName = streams.logStreams[0].logStreamName;
      const result = aws(profile, [
        "logs",
        "get-log-events",
        "--log-group-name",
        logGroup,
        "--log-stream-name",
        streamName,
        "--limit",
        String(limit),
      ]);
      const lines = result.events.map(
        (e) => `[${new Date(e.timestamp).toISOString()}] ${e.message}`
      );
      return ok(
        `Stream: ${streamName}\n\n${lines.length > 0 ? lines.join("\n") : "No events."}`
      );
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// EC2
// ==========================================================================

registerTool(ctx, {
  name: "list_ec2_instances",
  klass: "observability",
  description: "List EC2 instances, optionally filtered by Name tag pattern",
  schema: {
    env: EnvSchema,
    name_filter: SafeName.optional().describe(
      "Name tag glob filter (e.g. '*portal*', '*ngfw*')"
    ),
    include_terminated: z
      .boolean()
      .default(false)
      .describe("Include terminated instances (default false)"),
  },
  handler: async ({ env, name_filter, include_terminated }) => {
    try {
      const profile = getProfile(env);
      const filters = buildInstanceFilters({ name_filter, include_terminated });
      const result = aws(profile, [
        "ec2",
        "describe-instances",
        "--filters",
        JSON.stringify(filters),
        "--query",
        "Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,Name:Tags[?Key==`Name`].Value|[0],PrivateIp:PrivateIpAddress,Type:InstanceType}",
      ]);
      return ok(JSON.stringify(result, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "start_ec2_instance",
  klass: "infra_mutation",
  description: "Start a stopped EC2 instance",
  schema: {
    env: EnvSchema,
    instance_id: Ec2Id.describe("EC2 instance ID"),
  },
  handler: async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, [
        "ec2",
        "start-instances",
        "--instance-ids",
        instance_id,
      ]);
      const state = result.StartingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "stop_ec2_instance",
  klass: "infra_mutation",
  description: "Stop a running EC2 instance",
  schema: {
    env: EnvSchema,
    instance_id: Ec2Id.describe("EC2 instance ID"),
  },
  handler: async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, [
        "ec2",
        "stop-instances",
        "--instance-ids",
        instance_id,
      ]);
      const state = result.StoppingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "terminate_ec2_instance",
  klass: "infra_mutation",
  description: "Terminate an EC2 instance (irreversible)",
  schema: {
    env: EnvSchema,
    instance_id: Ec2Id.describe("EC2 instance ID"),
  },
  handler: async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, [
        "ec2",
        "terminate-instances",
        "--instance-ids",
        instance_id,
      ]);
      const state =
        result.TerminatingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// ECS
// ==========================================================================

registerTool(ctx, {
  name: "list_ecs_tasks",
  klass: "observability",
  description: "List running ECS tasks in a cluster",
  schema: {
    env: EnvSchema,
    cluster: SafeName.optional().describe(
      "ECS cluster name (defaults to {env}-portal)"
    ),
  },
  handler: async ({ env, cluster }) => {
    try {
      const profile = getProfile(env);
      const clusterName = cluster || `${env}-portal`;
      const tasks = aws(profile, [
        "ecs",
        "list-tasks",
        "--cluster",
        clusterName,
      ]);
      if (!tasks.taskArns || tasks.taskArns.length === 0) {
        return ok(`No running tasks in cluster ${clusterName}.`);
      }
      const details = aws(profile, [
        "ecs",
        "describe-tasks",
        "--cluster",
        clusterName,
        "--tasks",
        ...tasks.taskArns,
      ]);
      const summary = details.tasks.map((t) => ({
        taskId: t.taskArn.split("/").pop(),
        status: t.lastStatus,
        group: t.group,
        startedAt: t.startedAt,
      }));
      return ok(JSON.stringify(summary, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "describe_ecs_service",
  klass: "observability",
  description: "Describe an ECS service: task counts, deployment status, load balancers, and recent events.",
  schema: {
    env: EnvSchema,
    service: SafeName.describe("ECS service name"),
    cluster: SafeName.optional().describe(
      "ECS cluster name (defaults to {env}-portal)",
    ),
  },
  handler: async ({ env, service, cluster }) => {
    try {
      const profile = getProfile(env);
      const clusterName = cluster || `${env}-portal`;
      const result = aws(profile, [
        "ecs",
        "describe-services",
        "--cluster",
        clusterName,
        "--services",
        service,
      ]);
      const svc = result.services?.[0];
      if (!svc) return ok(`Service "${service}" not found in cluster ${clusterName}.`);
      const summary = {
        name: svc.serviceName,
        status: svc.status,
        desired: svc.desiredCount,
        running: svc.runningCount,
        pending: svc.pendingCount,
        launch_type: svc.launchType,
        deployments: (svc.deployments || []).map((d) => ({
          id: d.id,
          status: d.status,
          desired: d.desiredCount,
          running: d.runningCount,
          pending: d.pendingCount,
          rollout_state: d.rolloutState,
          created: d.createdAt,
          updated: d.updatedAt,
        })),
        load_balancers: svc.loadBalancers || [],
        events: (svc.events || []).slice(0, 10).map((e) => ({
          at: e.createdAt,
          message: e.message,
        })),
      };
      return ok(JSON.stringify(summary, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "restart_ecs_service",
  klass: "infra_mutation",
  description: "Force a new deployment of an ECS service (rolls all tasks).",
  schema: {
    env: EnvSchema,
    service: SafeName.describe("ECS service name"),
    cluster: SafeName.optional().describe(
      "ECS cluster name (defaults to {env}-portal)",
    ),
  },
  handler: async ({ env, service, cluster }) => {
    try {
      const profile = getProfile(env);
      const clusterName = cluster || `${env}-portal`;
      const result = aws(profile, [
        "ecs",
        "update-service",
        "--cluster",
        clusterName,
        "--service",
        service,
        "--force-new-deployment",
      ]);
      const svc = result.service;
      const deployment = svc.deployments?.find((d) => d.status === "PRIMARY");
      return ok(
        JSON.stringify(
          {
            service: svc.serviceName,
            status: svc.status,
            deployment_id: deployment?.id,
            rollout_state: deployment?.rolloutState,
            desired: svc.desiredCount,
          },
          null,
          2,
        ),
      );
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Secrets Manager
// ==========================================================================

registerTool(ctx, {
  name: "list_secrets",
  // Codex review #1201 cycle 3 finding 1: list_secrets returns only
  // metadata (name + lastChanged), no secret material. Classifying
  // it as secret_handle would wrap the metadata JSON into an opaque
  // `shf-secret:<uuid>` handle that the agent has no way to resolve
  // back to a discoverable list of secret IDs — breaking the
  // purpose of the list operation. The data is non-sensitive
  // discovery output, so observability is the correct class.
  klass: "observability",
  description: "List secrets in Secrets Manager",
  schema: { env: EnvSchema },
  handler: async ({ env }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, ["secretsmanager", "list-secrets"]);
      const secrets = result.SecretList.map((s) => ({
        name: s.Name,
        lastChanged: s.LastChangedDate,
      }));
      return ok(JSON.stringify(secrets, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "get_secret",
  klass: "secret_handle",
  description: "Get a secret value from Secrets Manager",
  schema: {
    env: EnvSchema,
    secret_id: SecretIdSchema.describe("Secret name or ARN"),
  },
  handler: async ({ env, secret_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, [
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        secret_id,
      ]);
      return ok(result.SecretString || "(binary secret)");
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// SSM
// ==========================================================================

registerTool(ctx, {
  name: "ssm_send_command",
  klass: "ssm_arbitrary",
  untrusted_inputs: ["command"],
  description: "Run a command on an EC2 instance via SSM. Auto-detects OS to use the correct shell (bash for Linux, PowerShell for Windows).",
  schema: {
    env: EnvSchema,
    instance_id: Ec2Id.describe("EC2 instance ID"),
    command: z.string().describe("Command to execute (shell for Linux, PowerShell for Windows)"),
  },
  handler: async ({ env, instance_id, command }) => {
    try {
      const profile = getProfile(env);
      const platform = getInstancePlatform(profile, instance_id);
      const docName = getSsmDocument(platform);
      const result = aws(
        profile,
        buildSsmSendCommandArgs({
          instanceId: instance_id,
          docName,
          commands: [command],
        })
      );
      const cmdId = result.Command.CommandId;
      return ok(
        `Command sent (${docName}). ID: ${cmdId}\nUse ssm_get_command_output to check results.`
      );
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "ssm_get_command_output",
  klass: "ssm_arbitrary",
  untrusted_source: "ssm_stdout",
  description: "Get the output of a previously sent SSM command",
  schema: {
    env: EnvSchema,
    command_id: SsmCommandId.describe("SSM command ID"),
    instance_id: Ec2Id.describe("EC2 instance ID the command was sent to"),
  },
  handler: async ({ env, command_id, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, [
        "ssm",
        "get-command-invocation",
        "--command-id",
        command_id,
        "--instance-id",
        instance_id,
      ]);
      return ok(
        `Status: ${result.Status}\n\n--- stdout ---\n${result.StandardOutputContent}\n--- stderr ---\n${result.StandardErrorContent}`
      );
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "start_portal_test_tunnel",
  klass: "dev_bypass_tunnel",
  description: "Start SSM tunnel to dev portal for testing. Enables dev_login access bypassing Cognito/MFA. Returns local URL.",
  schema: {
    env: z.literal("dev").describe("Environment (only 'dev' allowed)"),
    local_port: z.number().int().min(1024).max(65535).optional().describe("Local port (default: 8000)"),
  },
  handler: async ({ env, local_port = 8000 }) => {
    try {
      if (portalTunnels[env]) {
        return ok(`Tunnel already running on port ${portalTunnels[env].port}. Access at http://localhost:${portalTunnels[env].port}/dev-login/`);
      }

      const portInUse = await isPortOpen(local_port);
      if (portInUse) {
        return err(new Error(`Port ${local_port} already in use. Choose different port or stop existing tunnel.`));
      }

      const profile = getProfile(env);
      const instanceId = awsTextLib(
        profile,
        [
          "ec2",
          "describe-instances",
          "--filters",
          `Name=tag:Name,Values=${env}-portal-ec2`,
          "Name=instance-state-name,Values=running",
          "--query",
          "Reservations[0].Instances[0].InstanceId",
          "--output",
          "text",
        ],
        { timeoutMs: 30000 }
      );

      if (!instanceId || instanceId === "None") {
        return err(new Error(`Could not find running ${env} portal EC2 instance`));
      }

      const tunnelProc = spawnAws(
        profile,
        [
          "ssm",
          "start-session",
          "--target",
          instanceId,
          "--document-name",
          "AWS-StartPortForwardingSessionToRemoteHost",
          "--parameters",
          JSON.stringify({
            host: ["localhost"],
            portNumber: ["8000"],
            localPortNumber: [local_port.toString()],
          }),
        ],
        { stdio: ["ignore", "pipe", "pipe"] }
      );

      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          tunnelProc.kill();
          reject(new Error("Tunnel startup timeout"));
        }, 10000);

        let output = "";
        tunnelProc.stdout.on("data", (data) => {
          output += data.toString();
          if (output.includes("Waiting for connections")) {
            clearTimeout(timeout);
            resolve();
          }
        });

        tunnelProc.stderr.on("data", (data) => {
          const msg = data.toString();
          if (msg.includes("error") || msg.includes("failed")) {
            clearTimeout(timeout);
            reject(new Error(`Tunnel failed: ${msg}`));
          }
        });

        tunnelProc.on("error", (error) => {
          clearTimeout(timeout);
          reject(error);
        });

        tunnelProc.on("exit", (code) => {
          if (code !== 0 && code !== null) {
            clearTimeout(timeout);
            reject(new Error(`Tunnel exited with code ${code}`));
          }
        });
      });

      portalTunnels[env] = { process: tunnelProc, port: local_port };

      return ok(
        `Portal test tunnel started!\n\n` +
        `Access at: http://localhost:${local_port}/dev-login/\n\n` +
        `NOTES:\n` +
        `- Bypasses Cognito/MFA (dev_login checks ENVIRONMENT='development')\n` +
        `- If 400 error, ensure ALLOWED_HOSTS includes 'localhost' in dev\n` +
        `- Use stop_portal_test_tunnel when done\n` +
        `- Stays active until stopped or MCP restart`
      );
    } catch (e) {
      if (portalTunnels[env]) {
        portalTunnels[env].process.kill();
        delete portalTunnels[env];
      }
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "stop_portal_test_tunnel",
  klass: "dev_bypass_tunnel",
  description: "Stop SSM tunnel to dev portal",
  schema: {
    env: z.literal("dev").describe("Environment (only 'dev' allowed)"),
  },
  handler: async ({ env }) => {
    try {
      if (!portalTunnels[env]) {
        return ok("No tunnel running");
      }
      portalTunnels[env].process.kill();
      const port = portalTunnels[env].port;
      delete portalTunnels[env];
      return ok(`Portal test tunnel stopped (was on port ${port})`);
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// ASG / ELB
// ==========================================================================

registerTool(ctx, {
  name: "describe_asg",
  klass: "observability",
  description: "Show Auto Scaling Group status and instance refreshes",
  schema: {
    env: EnvSchema,
    asg_name: SafeName.optional().describe(
      "ASG name (defaults to {env}-portal-asg)"
    ),
  },
  handler: async ({ env, asg_name }) => {
    try {
      const profile = getProfile(env);
      const name = asg_name || `${env}-portal-asg`;
      const result = aws(profile, [
        "autoscaling",
        "describe-auto-scaling-groups",
        "--auto-scaling-group-names",
        name,
      ]);
      const asg = result.AutoScalingGroups[0];
      if (!asg) return ok(`ASG ${name} not found.`);
      const summary = {
        name: asg.AutoScalingGroupName,
        desired: asg.DesiredCapacity,
        min: asg.MinSize,
        max: asg.MaxSize,
        instances: asg.Instances.map((i) => ({
          id: i.InstanceId,
          state: i.LifecycleState,
          health: i.HealthStatus,
        })),
      };
      return ok(JSON.stringify(summary, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "describe_target_health",
  klass: "observability",
  description: "Show health status of targets in a target group",
  schema: {
    env: EnvSchema,
    target_group_arn: ArnSchema.describe("Target group ARN"),
  },
  handler: async ({ env, target_group_arn }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, [
        "elbv2",
        "describe-target-health",
        "--target-group-arn",
        target_group_arn,
      ]);
      const targets = result.TargetHealthDescriptions.map((t) => ({
        id: t.Target.Id,
        port: t.Target.Port,
        state: t.TargetHealth.State,
        reason: t.TargetHealth.Reason || "",
      }));
      return ok(JSON.stringify(targets, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Database tools
// ==========================================================================

registerTool(ctx, {
  name: "list_tables",
  klass: "db_arbitrary",
  description: "List all database tables with their service layer and row counts",
  schema: { env: EnvSchema },
  handler: async ({ env }) => {
    return withClient(env, { readOnly: true }, async (client) => {
      const result = await client.query(`
        SELECT t.tablename,
               pg_stat_get_live_tuples(c.oid) AS row_count
        FROM pg_tables t
        JOIN pg_class c ON c.relname = t.tablename
        WHERE t.schemaname = 'public'
        ORDER BY t.tablename
      `);

      const tables = result.rows.map((r) => ({
        table: r.tablename,
        service_layer: getServiceLayer(r.tablename),
        row_count: Number(r.row_count),
      }));

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(tables, null, 2),
          },
        ],
      };
    });
  },
});

registerTool(ctx, {
  name: "describe_table",
  klass: "db_arbitrary",
  description: "Show columns, types, nullability, and constraints for a table",
  schema: {
    table_name: z
      .string()
      .regex(/^[a-z_][a-z0-9_]*$/, "Must be a valid table name")
      .describe("Name of the table to describe"),
    env: EnvSchema,
  },
  handler: async ({ table_name, env }) => {
    return withClient(env, { readOnly: true }, async (client) => {
      const cols = await client.query(
        `SELECT column_name, data_type, is_nullable, column_default
         FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = $1
         ORDER BY ordinal_position`,
        [table_name]
      );

      if (cols.rows.length === 0) {
        return {
          content: [
            { type: "text", text: `Table '${table_name}' not found.` },
          ],
        };
      }

      const constraints = await client.query(
        `SELECT
           tc.constraint_name,
           tc.constraint_type,
           kcu.column_name,
           ccu.table_name AS foreign_table,
           ccu.column_name AS foreign_column
         FROM information_schema.table_constraints tc
         JOIN information_schema.key_column_usage kcu
           ON tc.constraint_name = kcu.constraint_name
           AND tc.table_schema = kcu.table_schema
         LEFT JOIN information_schema.constraint_column_usage ccu
           ON tc.constraint_name = ccu.constraint_name
           AND tc.table_schema = ccu.table_schema
         WHERE tc.table_name = $1 AND tc.table_schema = 'public'
         ORDER BY tc.constraint_type, kcu.column_name`,
        [table_name]
      );

      const indexes = await client.query(
        `SELECT indexname, indexdef
         FROM pg_indexes
         WHERE tablename = $1 AND schemaname = 'public'`,
        [table_name]
      );

      const output = {
        table: table_name,
        service_layer: getServiceLayer(table_name),
        columns: cols.rows,
        constraints: constraints.rows,
        indexes: indexes.rows,
      };

      return {
        content: [{ type: "text", text: JSON.stringify(output, null, 2) }],
      };
    });
  },
});

registerTool(ctx, {
  name: "query",
  klass: "db_arbitrary",
  untrusted_inputs: ["sql"],
  description: "Execute a read-only SQL query against the Shifter database",
  schema: {
    sql: z.string().describe("SQL query to execute (read-only)"),
    env: EnvSchema,
  },
  handler: async ({ sql, env }) => {
    if (FORBIDDEN_PATTERN.test(sql)) {
      return {
        content: [
          {
            type: "text",
            text: "Error: Only read-only queries (SELECT) are allowed. Write operations are blocked.",
          },
        ],
        isError: true,
      };
    }

    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const result = await client.query(sql);
        const output = {
          rows: result.rows,
          rowCount: result.rowCount,
          fields: result.fields?.map((f) => f.name),
        };

        return {
          content: [{ type: "text", text: JSON.stringify(output, null, 2) }],
        };
      });
    } catch (e) {
      return {
        content: [{ type: "text", text: `Query error: ${e.message}` }],
        isError: true,
      };
    }
  },
});

registerTool(ctx, {
  name: "execute",
  klass: "db_arbitrary",
  untrusted_inputs: ["sql"],
  is_write: true,
  description: "Execute a write SQL statement (UPDATE, INSERT, DELETE) against the Shifter database",
  schema: {
    sql: z.string().describe("SQL statement to execute"),
    env: EnvSchema,
  },
  handler: async ({ sql, env }) => {
    try {
      return await withClient(env, { readOnly: false }, async (client) => {
        const result = await client.query(sql);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                { rowCount: result.rowCount, command: result.command },
                null,
                2
              ),
            },
          ],
        };
      });
    } catch (e) {
      return {
        content: [{ type: "text", text: `Execute error: ${e.message}` }],
        isError: true,
      };
    }
  },
});

// ==========================================================================
// Range reconciliation
// ==========================================================================

registerTool(ctx, {
  name: "reconcile_ranges",
  klass: "infra_mutation",
  description: "Find orphaned EC2 range instances (running in AWS but belonging to failed/destroyed ranges). Dry-run by default; set execute=true to terminate and update DB.",
  schema: {
    env: EnvSchema,
    execute: z
      .boolean()
      .default(false)
      .describe(
        "Set to true to actually terminate instances and update DB. Default is dry-run."
      ),
  },
  handler: async ({ env, execute: shouldExecute }) => {
    try {
      const profile = getProfile(env);

      // 1. Get all running range instances from EC2 (filtered by shifter:range_id tag).
      // The shifter:range_id tag is set by Terraform common_tags on all range resources
      // and is absent from NGFW/portal instances, so it naturally scopes to ranges only.
      const filters = [
        { Name: "tag:shifter:range_id", Values: ["*"] },
        { Name: "instance-state-name", Values: ["running"] },
      ];
      const ec2Result = aws(profile, [
        "ec2",
        "describe-instances",
        "--filters",
        JSON.stringify(filters),
        "--query",
        "Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,Name:Tags[?Key==`Name`].Value|[0],RangeId:Tags[?Key==`shifter:range_id`].Value|[0]}",
      ]);

      const runningEc2s = ec2Result.filter(
        (i) => i.State === "running" && i.RangeId
      );

      if (runningEc2s.length === 0) {
        return ok("No running shifter range instances found in EC2.");
      }

      // 2. Query DB for engine_instances that map to these EC2 IDs
      const ec2Ids = runningEc2s.map((i) => i.InstanceId);

      const orphans = await withClient(
        env,
        { readOnly: true },
        async (client) => {
          const placeholders = ec2Ids
            .map((_, i) => `$${i + 1}`)
            .join(", ");
          const result = await client.query(
            `SELECT
              ei.id AS engine_instance_id,
              ei.status AS instance_status,
              ei.state->>'aws_instance_id' AS ec2_id,
              ei.role,
              ei.request_id AS engine_request_id,
              mcr.id AS range_id,
              mcr.status AS range_status
            FROM engine_instance ei
            LEFT JOIN mission_control_range mcr ON mcr.request_id = ei.request_id
            WHERE ei.state->>'aws_instance_id' IN (${placeholders})
              AND ei.deleted_at IS NULL`,
            ec2Ids
          );

          const dbMap = {};
          for (const row of result.rows) {
            dbMap[row.ec2_id] = row;
          }

          const found = [];
          for (const ec2 of runningEc2s) {
            const db = dbMap[ec2.InstanceId];
            if (!db) {
              // No engine_instance matched by aws_instance_id.
              // Use range_id from EC2 tag (set by Terraform on all range instances).
              const parsedRangeId = ec2.RangeId
                ? Number.parseInt(ec2.RangeId, 10)
                : null;

              // Look up the range and its engine_instances by parsed range_id
              const rangeResult = await client.query(
                `SELECT mcr.id AS range_id, mcr.status AS range_status,
                        mcr.request_id AS engine_request_id
                 FROM mission_control_range mcr
                 WHERE mcr.id = $1`,
                [parsedRangeId]
              );

              if (rangeResult.rows.length > 0) {
                const range = rangeResult.rows[0];

                // Only flag as orphan if range is in a terminal state
                if (range.range_status !== "failed" && range.range_status !== "destroyed") {
                  continue;
                }

                // Find pending engine_instances for this range (stuck with null aws_instance_id)
                const eiResult = range.engine_request_id
                  ? await client.query(
                      `SELECT ei.id AS engine_instance_id, ei.status, ei.role
                       FROM engine_instance ei
                       WHERE ei.request_id = $1 AND ei.deleted_at IS NULL`,
                      [range.engine_request_id]
                    )
                  : { rows: [] };

                found.push({
                  ec2_id: ec2.InstanceId,
                  ec2_name: ec2.Name,
                  reason: `no aws_instance_id match; range ${parsedRangeId} status: ${range.range_status}`,
                  engine_instance_id: null,
                  engine_instance_ids: eiResult.rows.map((r) => r.engine_instance_id),
                  engine_request_id: range.engine_request_id,
                  range_id: range.range_id,
                  range_status: range.range_status,
                });
              } else {
                // Range not found in DB at all - still an orphan EC2
                found.push({
                  ec2_id: ec2.InstanceId,
                  ec2_name: ec2.Name,
                  reason: `no aws_instance_id match; range ${parsedRangeId} not found in DB`,
                  engine_instance_id: null,
                  engine_request_id: null,
                  range_id: null,
                });
              }
            } else if (db.range_status == null) {
              // LEFT JOIN found engine_instance but no matching range — orphan
              found.push({
                ec2_id: ec2.InstanceId,
                ec2_name: ec2.Name,
                reason:
                  "engine_instance exists but no associated range found",
                engine_instance_id: db.engine_instance_id,
                engine_request_id: db.engine_request_id,
                range_id: null,
                instance_status: db.instance_status,
                role: db.role,
              });
            } else if (
              db.range_status === "failed" ||
              db.range_status === "destroyed"
            ) {
              found.push({
                ec2_id: ec2.InstanceId,
                ec2_name: ec2.Name,
                reason: `range status: ${db.range_status}`,
                engine_instance_id: db.engine_instance_id,
                engine_request_id: db.engine_request_id,
                range_id: db.range_id,
                instance_status: db.instance_status,
                role: db.role,
              });
            }
          }

          return found;
        }
      );

      if (orphans.length === 0) {
        return ok(
          `Checked ${runningEc2s.length} running EC2 instances. No orphans found.`
        );
      }

      if (!shouldExecute) {
        const report = {
          mode: "DRY RUN",
          orphaned_instances: orphans.length,
          details: orphans,
        };
        return ok(JSON.stringify(report, null, 2));
      }

      // 3. Execute: terminate EC2s and update DB
      const terminated = [];
      for (const orphan of orphans) {
        const termResult = aws(profile, [
          "ec2",
          "terminate-instances",
          "--instance-ids",
          orphan.ec2_id,
        ]);
        const state =
          termResult.TerminatingInstances?.[0]?.CurrentState?.Name;
        terminated.push({ ec2_id: orphan.ec2_id, state });
      }

      await withClient(env, { readOnly: false }, async (client) => {
        // Collect all engine_instance IDs to mark destroyed
        // - single engine_instance_id from direct aws_instance_id match
        // - engine_instance_ids array from Name-tag-resolved orphans
        const engineIds = [];
        for (const o of orphans) {
          if (o.engine_instance_id) {
            engineIds.push(o.engine_instance_id);
          }
          if (o.engine_instance_ids) {
            engineIds.push(...o.engine_instance_ids);
          }
        }
        const uniqueEngineIds = [...new Set(engineIds)];

        if (uniqueEngineIds.length > 0) {
          const ph = uniqueEngineIds.map((_, i) => `$${i + 1}`).join(", ");
          await client.query(
            `UPDATE engine_instance
             SET status = 'destroyed', destroyed_at = NOW(), deleted_at = NOW(), updated_at = NOW()
             WHERE id IN (${ph})`,
            uniqueEngineIds
          );
        }

        const rangeIds = [
          ...new Set(
            orphans.filter((o) => o.range_id).map((o) => o.range_id)
          ),
        ];
        if (rangeIds.length > 0) {
          const ph = rangeIds.map((_, i) => `$${i + 1}`).join(", ");
          await client.query(
            `UPDATE mission_control_range
             SET status = 'destroyed', destroyed_at = NOW(), updated_at = NOW()
             WHERE id IN (${ph}) AND status != 'destroyed'`,
            rangeIds
          );
        }

        const engineRequestIds = [
          ...new Set(
            orphans
              .filter((o) => o.engine_request_id)
              .map((o) => o.engine_request_id)
          ),
        ];
        if (engineRequestIds.length > 0) {
          const ph = engineRequestIds
            .map((_, i) => `$${i + 1}`)
            .join(", ");
          await client.query(
            `UPDATE cms_request SET deleted_at = NOW()
             WHERE deleted_at IS NULL
               AND request_id IN (
                 SELECT request_id FROM engine_request WHERE id IN (${ph})
               )`,
            engineRequestIds
          );
          await client.query(
            `UPDATE cms_rangeinstance SET deleted_at = NOW()
             WHERE deleted_at IS NULL
               AND request_id IN (
                 SELECT cr.id FROM cms_request cr
                 JOIN engine_request er ON er.request_id = cr.request_id
                 WHERE er.id IN (${ph})
               )`,
            engineRequestIds
          );
        }
      });

      const allEngineIds = [];
      for (const o of orphans) {
        if (o.engine_instance_id) allEngineIds.push(o.engine_instance_id);
        if (o.engine_instance_ids) allEngineIds.push(...o.engine_instance_ids);
      }

      const report = {
        mode: "EXECUTED",
        terminated: terminated.length,
        details: terminated,
        db_updates: {
          engine_instances: new Set(allEngineIds).size,
          ranges: [
            ...new Set(
              orphans.filter((o) => o.range_id).map((o) => o.range_id)
            ),
          ].length,
        },
      };
      return ok(JSON.stringify(report, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Risk Register
// ==========================================================================

const SeveritySchema = z
  .enum(["critical", "high", "medium", "low"])
  .describe("Risk severity: critical, high, medium, or low");

const StatusSchema = z
  .enum(["open", "acknowledged", "mitigating", "resolved", "closed"])
  .describe(
    "Risk lifecycle status: open, acknowledged, mitigating, resolved, or closed"
  );

const StrideSchema = z
  .array(z.enum(["S", "T", "R", "I", "D", "E"]))
  .describe(
    "STRIDE threat categories: S=Spoofing, T=Tampering, R=Repudiation, I=Information Disclosure, D=Denial of Service, E=Elevation of Privilege"
  );

const ScoreSchema = z
  .number()
  .int()
  .min(1)
  .max(5)
  .describe("Score from 1 (lowest) to 5 (highest)");

registerTool(ctx, {
  name: "list_risks",
  klass: "named_db_read",
  description: "List risk register entries. Returns active (non-deleted) risks by default, with computed risk_score and comment_count. Use filters to narrow results.",
  schema: {
    status: StatusSchema.optional().describe("Filter by lifecycle status"),
    severity: SeveritySchema.optional().describe("Filter by severity level"),
    include_deleted: z
      .boolean()
      .default(false)
      .describe("Include soft-deleted risks (default: false)"),
    env: EnvSchema,
  },
  handler: async ({ status, severity, include_deleted, env }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const conditions = [];
        const params = [];
        let paramIdx = 1;

        if (!include_deleted) {
          conditions.push("r.deleted_at IS NULL");
        }
        if (status) {
          conditions.push(`r.status = $${paramIdx}`);
          params.push(status);
          paramIdx++;
        }
        if (severity) {
          conditions.push(`r.severity = $${paramIdx}`);
          params.push(severity);
          paramIdx++;
        }

        const where =
          conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

        const result = await client.query(
          `SELECT r.id, r.title, r.severity, r.status,
                  r.stride_categories, r.likelihood_score, r.impact_score,
                  r.likelihood_score * r.impact_score AS risk_score,
                  r.created_at, r.updated_at, r.deleted_at,
                  (SELECT COUNT(*) FROM ${RISK_TABLES.comment} c
                   WHERE c.risk_id = r.id AND c.deleted_at IS NULL) AS comment_count
           FROM ${RISK_TABLES.risk} r
           ${where}
           ORDER BY r.created_at DESC`,
          params
        );

        return ok(
          JSON.stringify(
            { count: result.rowCount, risks: result.rows },
            null,
            2
          )
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "get_risk",
  klass: "named_db_read",
  description: "Get a single risk by ID with full details, including all comments and recent audit history.",
  schema: {
    risk_id: z.number().int().positive().describe("Risk ID"),
    env: EnvSchema,
  },
  handler: async ({ risk_id, env }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const riskResult = await client.query(
          `SELECT r.*,
                  r.likelihood_score * r.impact_score AS risk_score
           FROM ${RISK_TABLES.risk} r
           WHERE r.id = $1`,
          [risk_id]
        );

        if (riskResult.rows.length === 0) {
          return {
            content: [{ type: "text", text: `Risk ${risk_id} not found.` }],
            isError: true,
          };
        }

        const commentsResult = await client.query(
          `SELECT c.id, c.content, c.parent_comment_id, c.created_at,
                  COALESCE(u.email, 'API: ' || ak.name, 'Unknown') AS author
           FROM ${RISK_TABLES.comment} c
           LEFT JOIN auth_user u ON c.author_user_id = u.id
           LEFT JOIN ${RISK_TABLES.apikey} ak ON c.author_apikey_id = ak.id
           WHERE c.risk_id = $1 AND c.deleted_at IS NULL
           ORDER BY c.created_at`,
          [risk_id]
        );

        const auditResult = await client.query(
          `SELECT action, timestamp, previous_state, new_state, context
           FROM ${RISK_TABLES.audit_log}
           WHERE entity_type = 'risk' AND entity_id = $1
           ORDER BY timestamp DESC
           LIMIT 20`,
          [risk_id]
        );

        return ok(
          JSON.stringify(
            {
              risk: riskResult.rows[0],
              comments: commentsResult.rows,
              audit_log: auditResult.rows,
            },
            null,
            2
          )
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "create_risk",
  klass: "named_db_write",
  description: "Create a new risk register entry. Only title and description are required; all other fields have sensible defaults.",
  schema: {
    title: z.string().min(1).max(200).describe("Short title for the risk"),
    description: z.string().min(1).describe("Detailed risk description"),
    severity: SeveritySchema.default("medium").describe(
      "Severity level (default: medium)"
    ),
    status: StatusSchema.default("open").describe(
      "Initial status (default: open)"
    ),
    stride_categories: StrideSchema.default([]).describe(
      "STRIDE threat categories (default: none)"
    ),
    likelihood_score: ScoreSchema.nullable()
      .default(null)
      .describe("Likelihood score 1-5 (optional)"),
    impact_score: ScoreSchema.nullable()
      .default(null)
      .describe("Impact score 1-5 (optional)"),
    attack_vector: z
      .string()
      .default("")
      .describe("How the threat could be exploited (optional)"),
    affected_assets: z
      .string()
      .default("")
      .describe("What systems/assets are affected (optional)"),
    mitigation_status: z
      .string()
      .default("")
      .describe("Current mitigation efforts (optional)"),
    env: EnvSchema,
  },
  handler: async ({
    title,
    description,
    severity,
    status,
    stride_categories,
    likelihood_score,
    impact_score,
    attack_vector,
    affected_assets,
    mitigation_status,
    env,
  }) => {
    try {
      return await withClient(env, { readOnly: false }, async (client) => {
        const result = await client.query(
          `INSERT INTO ${RISK_TABLES.risk}
             (title, description, severity, status, stride_categories,
              likelihood_score, impact_score, attack_vector, affected_assets,
              mitigation_status, resolution_reason, created_at, updated_at)
           VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, '', NOW(), NOW())
           RETURNING *,
             likelihood_score * impact_score AS risk_score`,
          [
            title,
            description,
            severity,
            status,
            JSON.stringify(stride_categories),
            likelihood_score,
            impact_score,
            attack_vector,
            affected_assets,
            mitigation_status,
          ]
        );

        return ok(
          JSON.stringify({ created: true, risk: result.rows[0] }, null, 2)
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "update_risk",
  klass: "named_db_write",
  description: "Update one or more fields on an existing risk. Only provide the fields you want to change. Returns the full updated risk.",
  schema: {
    risk_id: z.number().int().positive().describe("Risk ID to update"),
    title: z
      .string()
      .min(1)
      .max(200)
      .optional()
      .describe("New title (optional)"),
    description: z
      .string()
      .min(1)
      .optional()
      .describe("New description (optional)"),
    severity: SeveritySchema.optional().describe("New severity (optional)"),
    status: StatusSchema.optional().describe("New status (optional)"),
    stride_categories: StrideSchema.optional().describe(
      "New STRIDE categories (optional)"
    ),
    likelihood_score: ScoreSchema.nullable()
      .optional()
      .describe("New likelihood score 1-5, or null to clear (optional)"),
    impact_score: ScoreSchema.nullable()
      .optional()
      .describe("New impact score 1-5, or null to clear (optional)"),
    attack_vector: z
      .string()
      .optional()
      .describe("New attack vector (optional)"),
    affected_assets: z
      .string()
      .optional()
      .describe("New affected assets (optional)"),
    mitigation_status: z
      .string()
      .optional()
      .describe("New mitigation status (optional)"),
    resolution_reason: z
      .string()
      .optional()
      .describe("Reason for resolution/closure (optional)"),
    env: EnvSchema,
  },
  handler: async ({
    risk_id,
    title,
    description,
    severity,
    status,
    stride_categories,
    likelihood_score,
    impact_score,
    attack_vector,
    affected_assets,
    mitigation_status,
    resolution_reason,
    env,
  }) => {
    const fieldMap = {
      title,
      description,
      severity,
      status,
      likelihood_score,
      impact_score,
      attack_vector,
      affected_assets,
      mitigation_status,
      resolution_reason,
    };

    if (stride_categories !== undefined) {
      fieldMap.stride_categories = JSON.stringify(stride_categories);
    }

    let updateInfo;
    try {
      updateInfo = buildUpdateSet(fieldMap);
    } catch {
      return {
        content: [
          {
            type: "text",
            text: "Error: No fields provided to update. Provide at least one field to change.",
          },
        ],
        isError: true,
      };
    }

    try {
      return await withClient(env, { readOnly: false }, async (client) => {
        let setClause = `${updateInfo.setClause}, updated_at = NOW()`;
        if (stride_categories !== undefined) {
          setClause = setClause.replace(
            /stride_categories = \$(\d+)/,
            (_, n) => `stride_categories = $${n}::jsonb`
          );
        }

        const result = await client.query(
          `UPDATE ${RISK_TABLES.risk}
           SET ${setClause}
           WHERE id = $${updateInfo.nextParam} AND deleted_at IS NULL
           RETURNING *, likelihood_score * impact_score AS risk_score`,
          [...updateInfo.values, risk_id]
        );

        if (result.rows.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `Risk ${risk_id} not found or is deleted.`,
              },
            ],
            isError: true,
          };
        }

        return ok(
          JSON.stringify({ updated: true, risk: result.rows[0] }, null, 2)
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "delete_risk",
  klass: "named_db_write",
  description: "Soft-delete a risk (sets deleted_at timestamp). The risk can be restored later with restore_risk.",
  schema: {
    risk_id: z.number().int().positive().describe("Risk ID to soft-delete"),
    env: EnvSchema,
  },
  handler: async ({ risk_id, env }) => {
    try {
      return await withClient(env, { readOnly: false }, async (client) => {
        const result = await client.query(
          `UPDATE ${RISK_TABLES.risk}
           SET deleted_at = NOW(), updated_at = NOW()
           WHERE id = $1 AND deleted_at IS NULL
           RETURNING id, title`,
          [risk_id]
        );

        if (result.rows.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `Risk ${risk_id} not found or already deleted.`,
              },
            ],
            isError: true,
          };
        }

        return ok(
          JSON.stringify({ deleted: true, ...result.rows[0] }, null, 2)
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "restore_risk",
  klass: "named_db_write",
  description: "Restore a soft-deleted risk (clears deleted_at timestamp).",
  schema: {
    risk_id: z
      .number()
      .int()
      .positive()
      .describe("Risk ID to restore from soft-delete"),
    env: EnvSchema,
  },
  handler: async ({ risk_id, env }) => {
    try {
      return await withClient(env, { readOnly: false }, async (client) => {
        const result = await client.query(
          `UPDATE ${RISK_TABLES.risk}
           SET deleted_at = NULL, updated_at = NOW()
           WHERE id = $1 AND deleted_at IS NOT NULL
           RETURNING id, title`,
          [risk_id]
        );

        if (result.rows.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `Risk ${risk_id} not found or is not deleted.`,
              },
            ],
            isError: true,
          };
        }

        return ok(
          JSON.stringify({ restored: true, ...result.rows[0] }, null, 2)
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "add_risk_comment",
  klass: "named_db_write",
  description: "Add a comment to a risk. Comments are immutable once created.",
  schema: {
    risk_id: z
      .number()
      .int()
      .positive()
      .describe("Risk ID to comment on"),
    content: z.string().min(1).describe("Comment text"),
    env: EnvSchema,
  },
  handler: async ({ risk_id, content, env }) => {
    try {
      return await withClient(env, { readOnly: false }, async (client) => {
        const riskCheck = await client.query(
          `SELECT id FROM ${RISK_TABLES.risk} WHERE id = $1 AND deleted_at IS NULL`,
          [risk_id]
        );

        if (riskCheck.rows.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `Risk ${risk_id} not found or is deleted.`,
              },
            ],
            isError: true,
          };
        }

        const result = await client.query(
          `INSERT INTO ${RISK_TABLES.comment} (risk_id, content, created_at)
           VALUES ($1, $2, NOW())
           RETURNING id, risk_id, content, created_at`,
          [risk_id, content]
        );

        return ok(
          JSON.stringify({ created: true, comment: result.rows[0] }, null, 2)
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "delete_risk_comment",
  klass: "named_db_write",
  description: "Soft-delete a comment on a risk (sets deleted_at timestamp).",
  schema: {
    comment_id: z.number().int().positive().describe("Comment ID to delete"),
    env: EnvSchema,
  },
  handler: async ({ comment_id, env }) => {
    try {
      return await withClient(env, { readOnly: false }, async (client) => {
        const result = await client.query(
          `UPDATE ${RISK_TABLES.comment}
           SET deleted_at = NOW()
           WHERE id = $1 AND deleted_at IS NULL
           RETURNING id, risk_id`,
          [comment_id]
        );

        if (result.rows.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `Comment ${comment_id} not found or already deleted.`,
              },
            ],
            isError: true,
          };
        }

        return ok(
          JSON.stringify({ deleted: true, ...result.rows[0] }, null, 2)
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "risk_dashboard",
  klass: "observability",
  description: "Get a summary dashboard of the risk register: total counts, breakdown by severity and status, top risks by score, and recent activity.",
  schema: {
    env: EnvSchema,
  },
  handler: async ({ env }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const totals = await client.query(
          `SELECT
             COUNT(*) FILTER (WHERE deleted_at IS NULL) AS active_risks,
             COUNT(*) FILTER (WHERE deleted_at IS NOT NULL) AS deleted_risks
           FROM ${RISK_TABLES.risk}`
        );

        const bySeverity = await client.query(
          `SELECT severity, COUNT(*) AS count
           FROM ${RISK_TABLES.risk}
           WHERE deleted_at IS NULL
           GROUP BY severity
           ORDER BY CASE severity
             WHEN 'critical' THEN 1 WHEN 'high' THEN 2
             WHEN 'medium' THEN 3 WHEN 'low' THEN 4 END`
        );

        const byStatus = await client.query(
          `SELECT status, COUNT(*) AS count
           FROM ${RISK_TABLES.risk}
           WHERE deleted_at IS NULL
           GROUP BY status
           ORDER BY CASE status
             WHEN 'open' THEN 1 WHEN 'acknowledged' THEN 2
             WHEN 'mitigating' THEN 3 WHEN 'resolved' THEN 4
             WHEN 'closed' THEN 5 END`
        );

        const topRisks = await client.query(
          `SELECT id, title, severity, status,
                  likelihood_score, impact_score,
                  likelihood_score * impact_score AS risk_score
           FROM ${RISK_TABLES.risk}
           WHERE deleted_at IS NULL
             AND likelihood_score IS NOT NULL
             AND impact_score IS NOT NULL
           ORDER BY risk_score DESC, created_at DESC
           LIMIT 10`
        );

        const recentAudit = await client.query(
          `SELECT al.action, al.entity_type, al.entity_id,
                  al.timestamp, al.context
           FROM ${RISK_TABLES.audit_log} al
           ORDER BY al.timestamp DESC
           LIMIT 10`
        );

        return ok(
          JSON.stringify(
            {
              totals: totals.rows[0],
              by_severity: bySeverity.rows,
              by_status: byStatus.rows,
              top_risks_by_score: topRisks.rows,
              recent_activity: recentAudit.rows,
            },
            null,
            2
          )
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "risk_matrix",
  klass: "observability",
  description: "Get a 5x5 risk matrix (likelihood vs impact). Each cell shows the count of risks and their titles. Useful for visualizing risk distribution.",
  schema: {
    env: EnvSchema,
  },
  handler: async ({ env }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const result = await client.query(
          `SELECT likelihood_score, impact_score,
                  COUNT(*) AS count,
                  json_agg(json_build_object(
                    'id', id, 'title', title, 'severity', severity
                  ) ORDER BY id) AS risks
           FROM ${RISK_TABLES.risk}
           WHERE deleted_at IS NULL
             AND likelihood_score IS NOT NULL
             AND impact_score IS NOT NULL
           GROUP BY likelihood_score, impact_score
           ORDER BY likelihood_score DESC, impact_score DESC`
        );

        const matrix = {};
        for (let l = 1; l <= 5; l++) {
          matrix[l] = {};
          for (let i = 1; i <= 5; i++) {
            matrix[l][i] = { count: 0, score: l * i, risks: [] };
          }
        }
        for (const row of result.rows) {
          matrix[row.likelihood_score][row.impact_score] = {
            count: Number(row.count),
            score: row.likelihood_score * row.impact_score,
            risks: row.risks,
          };
        }

        return ok(
          JSON.stringify(
            {
              description:
                "5x5 risk matrix. Outer key = likelihood (1-5), inner key = impact (1-5). Score = likelihood × impact.",
              matrix,
            },
            null,
            2
          )
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "risk_audit_log",
  klass: "named_db_read",
  description: "Get the audit history for a specific risk, showing all state changes with timestamps, actions, and before/after state snapshots.",
  schema: {
    risk_id: z
      .number()
      .int()
      .positive()
      .describe("Risk ID to get audit history for"),
    limit: z
      .number()
      .int()
      .min(1)
      .max(100)
      .default(50)
      .describe("Max entries to return (default: 50, max: 100)"),
    env: EnvSchema,
  },
  handler: async ({ risk_id, limit, env }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const result = await client.query(
          `SELECT action, actor_type, actor_id,
                  timestamp, previous_state, new_state, context
           FROM ${RISK_TABLES.audit_log}
           WHERE entity_type = 'risk' AND entity_id = $1
           ORDER BY timestamp DESC
           LIMIT $2`,
          [risk_id, limit]
        );

        return ok(
          JSON.stringify(
            {
              risk_id,
              entry_count: result.rowCount,
              entries: result.rows,
            },
            null,
            2
          )
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// S3
// ==========================================================================

registerTool(ctx, {
  name: "list_s3_buckets",
  klass: "observability",
  description: "List S3 buckets in the account, optionally filtered by name pattern.",
  schema: {
    env: EnvSchema,
    name_filter: z
      .string()
      .optional()
      .describe("Substring filter for bucket names"),
  },
  handler: async ({ env, name_filter }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, ["s3api", "list-buckets"]);
      let buckets = (result.Buckets || []).map((b) => ({
        name: b.Name,
        created: b.CreationDate,
      }));
      if (name_filter) {
        const lower = name_filter.toLowerCase();
        buckets = buckets.filter((b) => b.name.toLowerCase().includes(lower));
      }
      if (buckets.length === 0) return ok("No buckets found.");
      return ok(JSON.stringify(buckets, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "list_s3_objects",
  klass: "observability",
  // Codex review #1201 cycle 2: an authenticated principal with
  // write access to a bucket the operator inspects can name objects
  // with prompt-injection payloads, so the returned keys are
  // attacker-controlled. Fence the response.
  untrusted_source: "s3",
  description: "List objects in an S3 bucket with optional prefix filter. Returns key, size, and last modified.",
  schema: {
    env: EnvSchema,
    bucket: z.string().describe("S3 bucket name"),
    prefix: z.string().optional().describe("Key prefix filter"),
    max_keys: z
      .number()
      .int()
      .min(1)
      .max(1000)
      .default(100)
      .describe("Maximum number of objects to return (default 100, max 1000)"),
  },
  handler: async ({ env, bucket, prefix, max_keys }) => {
    try {
      const profile = getProfile(env);
      const args = [
        "s3api",
        "list-objects-v2",
        "--bucket",
        bucket,
        "--max-items",
        String(max_keys),
      ];
      if (prefix) args.push("--prefix", prefix);
      const result = aws(profile, args);
      const objects = (result.Contents || []).map((o) => ({
        key: o.Key,
        size: o.Size,
        last_modified: o.LastModified,
      }));
      if (objects.length === 0) return ok("No objects found.");
      return ok(JSON.stringify(objects, null, 2));
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "get_s3_object",
  klass: "observability",
  untrusted_source: "s3",
  description: "Read the contents of an S3 object. Returns text content for text files, metadata only for binary files. 1MB size limit.",
  schema: {
    env: EnvSchema,
    bucket: z.string().describe("S3 bucket name"),
    key: z.string().describe("S3 object key"),
  },
  handler: async ({ env, bucket, key }) => {
    try {
      const profile = getProfile(env);
      // Check size first
      const head = aws(profile, [
        "s3api",
        "head-object",
        "--bucket",
        bucket,
        "--key",
        key,
      ]);
      const size = head.ContentLength;
      const contentType = head.ContentType || "";

      if (size > MAX_S3_READ_SIZE) {
        return ok(
          JSON.stringify(
            {
              error: "Object too large to read inline",
              size,
              max_size: MAX_S3_READ_SIZE,
              content_type: contentType,
              last_modified: head.LastModified,
            },
            null,
            2,
          ),
        );
      }

      if (isBinaryContentType(contentType)) {
        return ok(
          JSON.stringify(
            {
              message: "Binary file — metadata only",
              size,
              content_type: contentType,
              last_modified: head.LastModified,
            },
            null,
            2,
          ),
        );
      }

      const content = awsText(profile, [
        "s3",
        "cp",
        `s3://${bucket}/${key}`,
        "-",
      ]);
      return ok(content);
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Infrastructure State
// ==========================================================================

registerTool(ctx, {
  name: "terraform_state",
  klass: "observability",
  // Codex review #1201 cycle 2: tfstate is read from caller-selected
  // S3 objects, so resource/module/name strings can be attacker-
  // controlled (e.g. a Range ID that originated as user input flows
  // through to a tag value). Fence the response.
  untrusted_source: "s3",
  description: "List resources from a Terraform state file stored in S3. Shows resource types, names, and modules.",
  schema: {
    env: EnvSchema,
    bucket: z.string().optional().describe(
      "S3 bucket containing TF state (auto-detected from env if omitted)",
    ),
    key: z.string().optional().describe(
      "S3 key for the state file (auto-detected from env if omitted)",
    ),
  },
  handler: async ({ env, bucket, key }) => {
    try {
      const profile = getProfile(env);
      const stateBuckets = {
        dev: {
          bucket: "shifter-dev-infra-2080ea59-c141-4021-9ddd-11c77cd0574d",
          key: "global/github-runner/terraform.tfstate",
        },
        prod: {
          bucket: "shifter-infra-9f7d1dc4-7f0c-495b-9c03-624dfd5a8795",
          key: "shifter/prod/terraform.tfstate",
        },
      };
      const defaults = stateBuckets[env] || {};
      const b = bucket || defaults.bucket;
      const k = key || defaults.key;
      if (!b || !k) {
        return err(new Error("Could not determine state bucket/key. Provide bucket and key explicitly."));
      }
      const content = awsText(profile, [
        "s3",
        "cp",
        `s3://${b}/${k}`,
        "-",
      ]);
      const state = JSON.parse(content);
      const resources = (state.resources || []).map((r) => ({
        module: r.module || "(root)",
        type: r.type,
        name: r.name,
        provider: r.provider,
        instances: r.instances?.length || 0,
      }));
      return ok(
        JSON.stringify(
          {
            terraform_version: state.terraform_version,
            serial: state.serial,
            total_resources: resources.length,
            resources,
          },
          null,
          2,
        ),
      );
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Cost & Billing
// ==========================================================================

registerTool(ctx, {
  name: "cost_summary",
  klass: "observability",
  description: "Get AWS cost summary for a date range, broken down by service. Defaults to last 30 days.",
  schema: {
    env: EnvSchema,
    start_date: z
      .string()
      .optional()
      .describe("Start date YYYY-MM-DD (defaults to 30 days ago)"),
    end_date: z
      .string()
      .optional()
      .describe("End date YYYY-MM-DD (defaults to today)"),
  },
  handler: async ({ env, start_date, end_date }) => {
    try {
      const profile = getProfile(env);
      const end = end_date || new Date().toISOString().slice(0, 10);
      const start =
        start_date ||
        new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
      const result = aws(profile, [
        "ce",
        "get-cost-and-usage",
        "--time-period",
        `Start=${start},End=${end}`,
        "--granularity",
        "MONTHLY",
        "--metrics",
        "BlendedCost",
        "--group-by",
        "Type=DIMENSION,Key=SERVICE",
      ]);
      const periods = result.ResultsByTime || [];
      let total = 0;
      const services = {};
      for (const period of periods) {
        for (const group of period.Groups || []) {
          const svc = group.Keys[0];
          const amount = Number.parseFloat(group.Metrics.BlendedCost.Amount);
          total += amount;
          services[svc] = (services[svc] || 0) + amount;
        }
      }
      const sorted = Object.entries(services)
        .map(([name, amount]) => ({ service: name, amount: `$${amount.toFixed(2)}` }))
        .sort((a, b) => Number.parseFloat(b.amount.slice(1)) - Number.parseFloat(a.amount.slice(1)));
      return ok(
        JSON.stringify(
          { period: { start, end }, total: `$${total.toFixed(2)}`, by_service: sorted },
          null,
          2,
        ),
      );
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "daily_spend",
  klass: "observability",
  description: "Show daily AWS spend for the last N days. Useful for spotting spikes.",
  schema: {
    env: EnvSchema,
    days: z
      .number()
      .int()
      .min(1)
      .max(90)
      .default(7)
      .describe("Number of days to show (default 7, max 90)"),
  },
  handler: async ({ env, days }) => {
    try {
      const profile = getProfile(env);
      const end = new Date().toISOString().slice(0, 10);
      const start = new Date(Date.now() - days * 86400000)
        .toISOString()
        .slice(0, 10);
      const result = aws(profile, [
        "ce",
        "get-cost-and-usage",
        "--time-period",
        `Start=${start},End=${end}`,
        "--granularity",
        "DAILY",
        "--metrics",
        "BlendedCost",
      ]);
      const dataPoints = (result.ResultsByTime || []).map((p) => {
        const amount = Number.parseFloat(p.Total.BlendedCost.Amount);
        return {
          date: p.TimePeriod.Start,
          amount: `$${amount.toFixed(2)}`,
        };
      });
      const amounts = dataPoints.map((d) => Number.parseFloat(d.amount.slice(1)));
      const avg = amounts.length > 0 ? amounts.reduce((a, b) => a + b, 0) / amounts.length : 0;
      const total = amounts.reduce((a, b) => a + b, 0);
      return ok(
        JSON.stringify(
          {
            period: { start, end, days },
            total: `$${total.toFixed(2)}`,
            daily_average: `$${avg.toFixed(2)}`,
            daily: dataPoints,
          },
          null,
          2,
        ),
      );
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Django Management Commands
// ==========================================================================

registerTool(ctx, {
  name: "run_manage_command",
  klass: "ssm_named",
  untrusted_inputs: ["command"],
  description: "Run a Django manage.py command on the portal container via SSM. Only whitelisted read-only commands are allowed: check, showmigrations, diffsettings, inspectdb, dbshell, clearsessions, collectstatic, show_urls.",
  schema: {
    env: EnvSchema,
    command: z
      .string()
      .describe("Management command and arguments (e.g. 'showmigrations', 'check --deploy')"),
    instance_id: Ec2Id.optional().describe(
      "Portal EC2 instance ID (auto-detected if omitted)",
    ),
  },
  handler: async ({ env, command, instance_id }) => {
    try {
      validateManageCommand(command);
      const profile = getProfile(env);

      // Auto-detect portal instance if not provided
      let targetId = instance_id;
      if (!targetId) {
        targetId = awsText(profile, [
          "ec2",
          "describe-instances",
          "--filters",
          "Name=tag:Name,Values=*portal*",
          "Name=instance-state-name,Values=running",
          "--query",
          "Reservations[0].Instances[0].InstanceId",
          "--output",
          "text",
        ]);
        if (!targetId || targetId === "None") {
          return err(new Error(`No running portal instance found in ${env}`));
        }
      }

      const result = aws(
        profile,
        buildRunManageArgs({ targetId, command })
      );
      const cmdId = result.Command.CommandId;
      return ok(
        `Command sent: manage.py ${command}\nInstance: ${targetId}\nCommand ID: ${cmdId}\nUse ssm_get_command_output to check results.`,
      );
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Range query tools
// ==========================================================================

registerTool(ctx, {
  name: "list_ranges",
  klass: "named_db_read",
  description: "List ranges with status, user, scenario, instance count, and timestamps. Useful for checking active/failed/destroyed ranges.",
  schema: {
    env: EnvSchema,
    status: z
      .string()
      .optional()
      .describe(
        "Filter by status (ready, failed, destroyed, provisioning, etc.)"
      ),
    user: z
      .string()
      .optional()
      .describe("Filter by username (substring match)"),
    limit: z
      .number()
      .int()
      .min(1)
      .max(100)
      .default(20)
      .describe("Max results to return (default 20)"),
  },
  handler: async ({ env, status, user, limit }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const conditions = [];
        const params = [];
        let paramIndex = 1;

        if (status) {
          conditions.push(`r.status = $${paramIndex++}`);
          params.push(status);
        }
        if (user) {
          conditions.push(`u.username ILIKE $${paramIndex++}`);
          params.push(`%${user}%`);
        }

        const where =
          conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

        params.push(limit);
        const limitParam = `$${paramIndex}`;

        const result = await client.query(
          `SELECT r.id, r.uuid, r.status,
                  r.range_config->>'scenario_id' AS scenario,
                  u.username,
                  r.subnet_cidr,
                  r.created_at, r.ready_at, r.destroyed_at,
                  r.request_id,
                  COUNT(i.id) AS instance_count
           FROM mission_control_range r
           LEFT JOIN auth_user u ON r.user_id = u.id
           LEFT JOIN engine_instance i ON i.request_id = r.request_id
           ${where}
           GROUP BY r.id, u.username
           ORDER BY r.created_at DESC
           LIMIT ${limitParam}`,
          params
        );

        return ok(JSON.stringify(result.rows, null, 2));
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "get_range",
  klass: "named_db_read",
  description: "Get detailed info for a single range including instances and subnet allocations.",
  schema: {
    env: EnvSchema,
    range_id: z.number().int().describe("The range ID"),
  },
  handler: async ({ env, range_id }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const rangeResult = await client.query(
          `SELECT r.id, r.uuid, r.status,
                  r.range_config->>'scenario_id' AS scenario,
                  r.range_config->>'scenario_name' AS scenario_name,
                  u.username,
                  r.subnet_cidr, r.subnet_id,
                  r.kali_ip::text, r.victim_ip::text,
                  r.kali_instance_id, r.victim_instance_id,
                  r.gwlb_endpoint_id, r.provisioner_version,
                  r.error_message,
                  r.created_at, r.ready_at, r.paused_at, r.destroyed_at,
                  r.request_id
           FROM mission_control_range r
           LEFT JOIN auth_user u ON r.user_id = u.id
           WHERE r.id = $1`,
          [range_id]
        );

        if (rangeResult.rows.length === 0) {
          return ok(`No range found with id ${range_id}`);
        }

        const range = rangeResult.rows[0];

        const instancesResult = await client.query(
          `SELECT i.id, i.uuid, i.status, i.role, i.os_type,
                  i.state->>'aws_instance_id' AS aws_instance_id,
                  i.state->>'private_ip' AS private_ip,
                  i.created_at, i.destroyed_at
           FROM engine_instance i
           WHERE i.request_id = $1
           ORDER BY i.role`,
          [range.request_id]
        );

        const subnetsResult = await client.query(
          `SELECT id, vpc_id, cidr, subnet_size, status,
                  reserved_at, confirmed_at, released_at
           FROM engine_subnetallocation
           WHERE request_id = $1`,
          [range.request_id]
        );

        return ok(
          JSON.stringify(
            {
              range,
              instances: instancesResult.rows,
              subnet_allocations: subnetsResult.rows,
            },
            null,
            2
          )
        );
      });
    } catch (e) {
      return err(e);
    }
  },
});

registerTool(ctx, {
  name: "list_subnet_allocations",
  klass: "named_db_read",
  description: "List subnet CIDR allocations. Useful for debugging race conditions and stale reservations.",
  schema: {
    env: EnvSchema,
    status: z
      .string()
      .optional()
      .describe("Filter by status (reserved, active, released)"),
    vpc_id: z.string().optional().describe("Filter by VPC ID"),
  },
  handler: async ({ env, status, vpc_id }) => {
    try {
      return await withClient(env, { readOnly: true }, async (client) => {
        const conditions = [];
        const params = [];
        let paramIndex = 1;

        if (status) {
          conditions.push(`sa.status = $${paramIndex++}`);
          params.push(status);
        }
        if (vpc_id) {
          conditions.push(`sa.vpc_id = $${paramIndex++}`);
          params.push(vpc_id);
        }

        const where =
          conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

        const result = await client.query(
          `SELECT sa.id, sa.vpc_id, sa.cidr, sa.subnet_size,
                  sa.range_id, sa.request_id, sa.status,
                  sa.reserved_at, sa.confirmed_at, sa.released_at
           FROM engine_subnetallocation sa
           ${where}
           ORDER BY sa.reserved_at DESC
           LIMIT 50`,
          params
        );

        return ok(JSON.stringify(result.rows, null, 2));
      });
    } catch (e) {
      return err(e);
    }
  },
});

// ==========================================================================
// Start server
// ==========================================================================

// Codex review #1201 cycle 1 finding 4: every `apex_operations[*].tool`
// rule in .shifter.yaml must point at a descriptor that actually
// reached registerTool. Run this AFTER every registerTool call so a
// typo in .shifter.yaml fails startup rather than silently disabling
// the intended apex gate.
validateApexCoverage(policy);

const transport = new StdioServerTransport();
await server.connect(transport);

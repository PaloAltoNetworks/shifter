#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { execSync, spawn } from "child_process";
import pg from "pg";
import net from "net";
import {
  REGION,
  LOCAL_PORTS,
  getServiceLayer,
  getProfile as _getProfile,
  FORBIDDEN_PATTERN,
  resolveLogGroup,
  buildInstanceFilters,
} from "./lib.js";

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
// ==========================================================================

function aws(profile, args) {
  const cmd = `aws ${args} --profile "${profile}" --region "${REGION}" --output json`;
  return JSON.parse(execSync(cmd, { encoding: "utf-8", timeout: 60000 }));
}

function awsText(profile, args) {
  const cmd = `aws ${args} --profile "${profile}" --region "${REGION}"`;
  return execSync(cmd, { encoding: "utf-8", timeout: 60000 }).trim();
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

  const result = execSync(
    `aws secretsmanager get-secret-value --secret-id "${secretId}" --region "${REGION}" --profile "${profile}" --query SecretString --output text`,
    { encoding: "utf-8", timeout: 30000 }
  );

  credentials[env] = JSON.parse(result.trim());
  return credentials[env];
}

function killTunnel(env) {
  if (tunnels[env]?.process) {
    tunnels[env].process.kill();
    delete tunnels[env];
  }
}

async function ensureTunnel(env) {
  const port = LOCAL_PORTS[env];

  if (tunnels[env]?.process && !tunnels[env].process.killed) {
    if (await isPortOpen(port)) return;
    killTunnel(env);
  }

  if (await isPortOpen(port)) return;

  const profile = getProfile(env);

  const instanceId = execSync(
    `aws ec2 describe-instances --filters "Name=tag:Name,Values=${env}-portal-ec2" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].InstanceId" --output text --region "${REGION}" --profile "${profile}"`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

  if (!instanceId || instanceId === "None") {
    throw new Error(`Could not find running ${env} portal EC2 instance`);
  }

  const jmesQuery = `DBInstances[?DBInstanceIdentifier==\`${env}-portal-db\`].Endpoint.Address`;
  const rdsHost = execSync(
    `aws rds describe-db-instances --region "${REGION}" --profile "${profile}" --query '${jmesQuery}' --output text`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

  if (!rdsHost || rdsHost === "None") {
    throw new Error(`Could not find RDS endpoint for ${env}`);
  }

  const proc = spawn(
    "aws",
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
      "--region",
      REGION,
      "--profile",
      profile,
    ],
    { stdio: ["ignore", "pipe", "pipe"] }
  );

  tunnels[env] = { process: proc };

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
    pools[env] = new Pool({
      host: "localhost",
      port: LOCAL_PORTS[env],
      user: creds.username,
      password: creds.password,
      database: creds.dbname,
      ssl: { rejectUnauthorized: false },
      max: 3,
      connectionTimeoutMillis: 10000,
      idleTimeoutMillis: 30000,
    });
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

const EnvSchema = z
  .enum(["dev", "prod"])
  .default("dev")
  .describe("Environment (dev or prod). Defaults to dev.");

// ==========================================================================
// CloudWatch Logs
// ==========================================================================

server.tool(
  "describe_log_streams",
  "List recent log streams for a component or log group. Use component shorthand (portal, provisioner, guacamole-client, guacd, network-firewall, rds) or a full log group path.",
  {
    env: EnvSchema,
    component: z
      .string()
      .describe(
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
  async ({ env, component, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(
        profile,
        `logs describe-log-streams --log-group-name "${logGroup}" --order-by LastEventTime --descending --limit ${limit}`
      );
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
  }
);

server.tool(
  "get_log_events",
  "Get log events from a specific log stream",
  {
    env: EnvSchema,
    component: z
      .string()
      .describe("Component shorthand or full log group path"),
    stream_name: z.string().describe("Log stream name"),
    limit: z
      .number()
      .int()
      .min(1)
      .max(200)
      .default(50)
      .describe("Number of events (default 50)"),
  },
  async ({ env, component, stream_name, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(
        profile,
        `logs get-log-events --log-group-name "${logGroup}" --log-stream-name "${stream_name}" --limit ${limit}`
      );
      const lines = result.events.map(
        (e) => `[${new Date(e.timestamp).toISOString()}] ${e.message}`
      );
      return ok(lines.join("\n"));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "filter_log_events",
  "Search log events across streams using a CloudWatch filter pattern",
  {
    env: EnvSchema,
    component: z
      .string()
      .describe("Component shorthand or full log group path"),
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
  async ({ env, component, filter_pattern, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(
        profile,
        `logs filter-log-events --log-group-name "${logGroup}" --filter-pattern ${JSON.stringify(filter_pattern)} --limit ${limit}`
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
  }
);

server.tool(
  "tail_logs",
  "Tail recent logs for a component (shortcut for describe_streams + get_log_events on the latest stream)",
  {
    env: EnvSchema,
    component: z
      .string()
      .describe("Component shorthand or full log group path"),
    limit: z
      .number()
      .int()
      .min(1)
      .max(200)
      .default(50)
      .describe("Number of events (default 50)"),
  },
  async ({ env, component, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const streams = aws(
        profile,
        `logs describe-log-streams --log-group-name "${logGroup}" --order-by LastEventTime --descending --limit 1`
      );
      if (!streams.logStreams || streams.logStreams.length === 0) {
        return ok("No log streams found.");
      }
      const streamName = streams.logStreams[0].logStreamName;
      const result = aws(
        profile,
        `logs get-log-events --log-group-name "${logGroup}" --log-stream-name "${streamName}" --limit ${limit}`
      );
      const lines = result.events.map(
        (e) => `[${new Date(e.timestamp).toISOString()}] ${e.message}`
      );
      return ok(
        `Stream: ${streamName}\n\n${lines.length > 0 ? lines.join("\n") : "No events."}`
      );
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// EC2
// ==========================================================================

server.tool(
  "list_ec2_instances",
  "List EC2 instances, optionally filtered by Name tag pattern",
  {
    env: EnvSchema,
    name_filter: z
      .string()
      .optional()
      .describe("Name tag glob filter (e.g. '*portal*', '*ngfw*')"),
    include_terminated: z
      .boolean()
      .default(false)
      .describe("Include terminated instances (default false)"),
  },
  async ({ env, name_filter, include_terminated }) => {
    try {
      const profile = getProfile(env);
      const filters = buildInstanceFilters({ name_filter, include_terminated });
      const filtersJson = JSON.stringify(JSON.stringify(filters));
      const result = aws(
        profile,
        `ec2 describe-instances --filters ${filtersJson} --query 'Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,Name:Tags[?Key==\`Name\`].Value|[0],PrivateIp:PrivateIpAddress,Type:InstanceType}'`
      );
      return ok(JSON.stringify(result, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "start_ec2_instance",
  "Start a stopped EC2 instance",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
  },
  async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `ec2 start-instances --instance-ids "${instance_id}"`
      );
      const state = result.StartingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "stop_ec2_instance",
  "Stop a running EC2 instance",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
  },
  async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `ec2 stop-instances --instance-ids "${instance_id}"`
      );
      const state = result.StoppingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "terminate_ec2_instance",
  "Terminate an EC2 instance (irreversible)",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
  },
  async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `ec2 terminate-instances --instance-ids "${instance_id}"`
      );
      const state =
        result.TerminatingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// ECS
// ==========================================================================

server.tool(
  "list_ecs_tasks",
  "List running ECS tasks in a cluster",
  {
    env: EnvSchema,
    cluster: z
      .string()
      .optional()
      .describe("ECS cluster name (defaults to {env}-portal)"),
  },
  async ({ env, cluster }) => {
    try {
      const profile = getProfile(env);
      const clusterName = cluster || `${env}-portal`;
      const tasks = aws(
        profile,
        `ecs list-tasks --cluster "${clusterName}"`
      );
      if (!tasks.taskArns || tasks.taskArns.length === 0) {
        return ok(`No running tasks in cluster ${clusterName}.`);
      }
      const arns = tasks.taskArns.map((a) => `"${a}"`).join(" ");
      const details = aws(
        profile,
        `ecs describe-tasks --cluster "${clusterName}" --tasks ${arns}`
      );
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
  }
);

// ==========================================================================
// Secrets Manager
// ==========================================================================

server.tool(
  "list_secrets",
  "List secrets in Secrets Manager",
  { env: EnvSchema },
  async ({ env }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, `secretsmanager list-secrets`);
      const secrets = result.SecretList.map((s) => ({
        name: s.Name,
        lastChanged: s.LastChangedDate,
      }));
      return ok(JSON.stringify(secrets, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "get_secret",
  "Get a secret value from Secrets Manager",
  {
    env: EnvSchema,
    secret_id: z.string().describe("Secret name or ARN"),
  },
  async ({ env, secret_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `secretsmanager get-secret-value --secret-id "${secret_id}"`
      );
      return ok(result.SecretString || "(binary secret)");
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// SSM
// ==========================================================================

server.tool(
  "ssm_send_command",
  "Run a shell command on an EC2 instance via SSM",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
    command: z.string().describe("Shell command to execute"),
  },
  async ({ env, instance_id, command }) => {
    try {
      const profile = getProfile(env);
      const params = JSON.stringify({ commands: [command] });
      const result = aws(
        profile,
        `ssm send-command --instance-ids "${instance_id}" --document-name AWS-RunShellScript --parameters '${params}'`
      );
      const cmdId = result.Command.CommandId;
      return ok(
        `Command sent. ID: ${cmdId}\nUse ssm_get_command_output to check results.`
      );
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "ssm_get_command_output",
  "Get the output of a previously sent SSM command",
  {
    env: EnvSchema,
    command_id: z.string().describe("SSM command ID"),
    instance_id: z
      .string()
      .describe("EC2 instance ID the command was sent to"),
  },
  async ({ env, command_id, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `ssm get-command-invocation --command-id "${command_id}" --instance-id "${instance_id}"`
      );
      return ok(
        `Status: ${result.Status}\n\n--- stdout ---\n${result.StandardOutputContent}\n--- stderr ---\n${result.StandardErrorContent}`
      );
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// ASG / ELB
// ==========================================================================

server.tool(
  "describe_asg",
  "Show Auto Scaling Group status and instance refreshes",
  {
    env: EnvSchema,
    asg_name: z
      .string()
      .optional()
      .describe("ASG name (defaults to {env}-portal-asg)"),
  },
  async ({ env, asg_name }) => {
    try {
      const profile = getProfile(env);
      const name = asg_name || `${env}-portal-asg`;
      const result = aws(
        profile,
        `autoscaling describe-auto-scaling-groups --auto-scaling-group-names "${name}"`
      );
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
  }
);

server.tool(
  "describe_target_health",
  "Show health status of targets in a target group",
  {
    env: EnvSchema,
    target_group_arn: z.string().describe("Target group ARN"),
  },
  async ({ env, target_group_arn }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `elbv2 describe-target-health --target-group-arn "${target_group_arn}"`
      );
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
  }
);

// ==========================================================================
// Database tools
// ==========================================================================

server.tool(
  "list_tables",
  "List all database tables with their service layer and row counts",
  { env: EnvSchema },
  async ({ env }) => {
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
  }
);

server.tool(
  "describe_table",
  "Show columns, types, nullability, and constraints for a table",
  {
    table_name: z.string().describe("Name of the table to describe"),
    env: EnvSchema,
  },
  async ({ table_name, env }) => {
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
  }
);

server.tool(
  "query",
  "Execute a read-only SQL query against the Shifter database",
  {
    sql: z.string().describe("SQL query to execute (read-only)"),
    env: EnvSchema,
  },
  async ({ sql, env }) => {
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
  }
);

server.tool(
  "execute",
  "Execute a write SQL statement (UPDATE, INSERT, DELETE) against the Shifter database",
  {
    sql: z.string().describe("SQL statement to execute"),
    env: EnvSchema,
  },
  async ({ sql, env }) => {
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
  }
);

// ==========================================================================
// Range reconciliation
// ==========================================================================

server.tool(
  "reconcile_ranges",
  "Find orphaned EC2 range instances (running in AWS but belonging to failed/destroyed ranges). Dry-run by default; set execute=true to terminate and update DB.",
  {
    env: EnvSchema,
    execute: z
      .boolean()
      .default(false)
      .describe(
        "Set to true to actually terminate instances and update DB. Default is dry-run."
      ),
  },
  async ({ env, execute: shouldExecute }) => {
    try {
      const profile = getProfile(env);

      // 1. Get all running shifter range instances from EC2 (exclude portal, ngfw)
      const filters = buildInstanceFilters({ name_filter: "shifter-*" });
      const filtersJson = JSON.stringify(JSON.stringify(filters));
      const ec2Result = aws(
        profile,
        `ec2 describe-instances --filters ${filtersJson} --query 'Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,Name:Tags[?Key==\`Name\`].Value|[0]}'`
      );

      // Only include EC2s matching shifter-{role}-{range_id} pattern (range instances)
      const rangeNamePattern = /^shifter-\w+-\d+$/;
      const runningEc2s = ec2Result.filter(
        (i) => i.State === "running" && rangeNamePattern.test(i.Name)
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
              // Parse range_id from EC2 Name tag (format: shifter-{role}-{range_id})
              const nameMatch = ec2.Name?.match(/^shifter-\w+-(\d+)$/);
              const parsedRangeId = nameMatch ? parseInt(nameMatch[1], 10) : null;

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
        const termResult = aws(
          profile,
          `ec2 terminate-instances --instance-ids "${orphan.ec2_id}"`
        );
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
  }
);

// ==========================================================================
// Start server
// ==========================================================================

const transport = new StdioServerTransport();
await server.connect(transport);

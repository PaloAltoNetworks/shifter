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
  SERVICE_LAYERS,
  LEGACY_TABLE_MAP,
  getServiceLayer,
  getProfile as _getProfile,
  FORBIDDEN_PATTERN,
} from "./lib.js";

const { Pool } = pg;

const PROFILES = {
  dev: process.env.PANW_SHIFTER_DEV_PROFILE,
  prod: process.env.PANW_SHIFTER_PROD_PROFILE,
};

function getProfile(env) {
  return _getProfile(PROFILES, env);
}

// --- Tunnel Management ---

const tunnels = {}; // env -> { process, ready }
const credentials = {}; // env -> { username, password, dbname }

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

  // If we already have this env's tunnel and port is open, we're good
  if (tunnels[env]?.process && !tunnels[env].process.killed) {
    if (await isPortOpen(port)) return;
    // Process exists but port dead — clean up and re-create
    killTunnel(env);
  }

  // If port is open but we don't own it, something external is using it — just use it
  if (await isPortOpen(port)) return;

  const profile = getProfile(env);

  // Get EC2 instance ID
  const instanceId = execSync(
    `aws ec2 describe-instances --filters "Name=tag:Name,Values=${env}-portal-ec2" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].InstanceId" --output text --region "${REGION}" --profile "${profile}"`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

  if (!instanceId || instanceId === "None") {
    throw new Error(`Could not find running ${env} portal EC2 instance`);
  }

  // Get RDS endpoint
  const jmesQuery = `DBInstances[?DBInstanceIdentifier==\`${env}-portal-db\`].Endpoint.Address`;
  const rdsHost = execSync(
    `aws rds describe-db-instances --region "${REGION}" --profile "${profile}" --query '${jmesQuery}' --output text`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

  if (!rdsHost || rdsHost === "None") {
    throw new Error(`Could not find RDS endpoint for ${env}`);
  }

  // Start SSM port forwarding
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

  // Wait for tunnel to be ready
  for (let i = 0; i < 30; i++) {
    if (await isPortOpen(port)) return;
    await new Promise((r) => setTimeout(r, 1000));
  }

  proc.kill();
  delete tunnels[env];
  throw new Error("Tunnel failed to start within 30 seconds");
}

const pools = {}; // env -> pg.Pool

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
      // Discard pool on background connection errors (e.g. tunnel drop)
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
      await client.query("SET default_transaction_read_only = OFF").catch(() => {});
    }
    client.release();
  }
}

// --- Cleanup ---

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

// --- MCP Server ---

const server = new McpServer({
  name: "shifter-db",
  version: "1.0.0",
});

const EnvSchema = z
  .enum(["dev", "prod"])
  .default("dev")
  .describe("Environment (dev or prod). Defaults to dev.");

// Tool: list_tables
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

// Tool: describe_table
server.tool(
  "describe_table",
  "Show columns, types, nullability, and constraints for a table",
  {
    table_name: z.string().describe("Name of the table to describe"),
    env: EnvSchema,
  },
  async ({ table_name, env }) => {
    return withClient(env, { readOnly: true }, async (client) => {
      // Columns
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

      // Constraints (PK, FK, unique)
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

      // Indexes
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

// Tool: query
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
    } catch (err) {
      return {
        content: [{ type: "text", text: `Query error: ${err.message}` }],
        isError: true,
      };
    }
  }
);

// Tool: execute
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
    } catch (err) {
      return {
        content: [{ type: "text", text: `Execute error: ${err.message}` }],
        isError: true,
      };
    }
  }
);

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);

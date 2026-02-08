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
  RISK_TABLES,
  buildUpdateSet,
} from "./lib.js";

const { Client } = pg;

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

async function getDbClient(env, { readOnly = true } = {}) {
  await ensureTunnel(env);
  const creds = await fetchCredentials(env);

  const client = new Client({
    host: "localhost",
    port: LOCAL_PORTS[env],
    user: creds.username,
    password: creds.password,
    database: creds.dbname,
    ssl: { rejectUnauthorized: false },
  });

  await client.connect();
  if (readOnly) {
    await client.query("SET default_transaction_read_only = ON");
  }
  return client;
}

// --- Cleanup ---

function cleanup() {
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
    const client = await getDbClient(env);
    try {
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
    } finally {
      await client.end();
    }
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
    const client = await getDbClient(env);
    try {
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
    } finally {
      await client.end();
    }
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

    const client = await getDbClient(env);
    try {
      const result = await client.query(sql);
      const output = {
        rows: result.rows,
        rowCount: result.rowCount,
        fields: result.fields?.map((f) => f.name),
      };

      return {
        content: [{ type: "text", text: JSON.stringify(output, null, 2) }],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Query error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
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
    const client = await getDbClient(env, { readOnly: false });
    try {
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
    } catch (err) {
      return {
        content: [{ type: "text", text: `Execute error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// ── Risk Register Tools ──────────────────────────────────────────────

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

// Tool: list_risks
server.tool(
  "list_risks",
  "List risk register entries. Returns active (non-deleted) risks by default, with computed risk_score and comment_count. Use filters to narrow results.",
  {
    status: StatusSchema.optional().describe("Filter by lifecycle status"),
    severity: SeveritySchema.optional().describe("Filter by severity level"),
    include_deleted: z
      .boolean()
      .default(false)
      .describe("Include soft-deleted risks (default: false)"),
    env: EnvSchema,
  },
  async ({ status, severity, include_deleted, env }) => {
    const client = await getDbClient(env);
    try {
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              { count: result.rowCount, risks: result.rows },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: get_risk
server.tool(
  "get_risk",
  "Get a single risk by ID with full details, including all comments and recent audit history.",
  {
    risk_id: z.number().int().positive().describe("Risk ID"),
    env: EnvSchema,
  },
  async ({ risk_id, env }) => {
    const client = await getDbClient(env);
    try {
      // Fetch risk
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

      // Fetch comments
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

      // Fetch recent audit entries
      const auditResult = await client.query(
        `SELECT action, timestamp, previous_state, new_state, context
         FROM ${RISK_TABLES.audit_log}
         WHERE entity_type = 'risk' AND entity_id = $1
         ORDER BY timestamp DESC
         LIMIT 20`,
        [risk_id]
      );

      const output = {
        risk: riskResult.rows[0],
        comments: commentsResult.rows,
        audit_log: auditResult.rows,
      };

      return {
        content: [{ type: "text", text: JSON.stringify(output, null, 2) }],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: create_risk
server.tool(
  "create_risk",
  "Create a new risk register entry. Only title and description are required; all other fields have sensible defaults.",
  {
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
  async ({
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
    const client = await getDbClient(env, { readOnly: false });
    try {
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              { created: true, risk: result.rows[0] },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: update_risk
server.tool(
  "update_risk",
  "Update one or more fields on an existing risk. Only provide the fields you want to change. Returns the full updated risk.",
  {
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
  async ({
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
    // Map provided params to DB column names
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

    // stride_categories needs JSON serialization
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

    const client = await getDbClient(env, { readOnly: false });
    try {
      // Add updated_at and cast stride_categories if present
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              { updated: true, risk: result.rows[0] },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: delete_risk
server.tool(
  "delete_risk",
  "Soft-delete a risk (sets deleted_at timestamp). The risk can be restored later with restore_risk.",
  {
    risk_id: z.number().int().positive().describe("Risk ID to soft-delete"),
    env: EnvSchema,
  },
  async ({ risk_id, env }) => {
    const client = await getDbClient(env, { readOnly: false });
    try {
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ deleted: true, ...result.rows[0] }, null, 2),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: restore_risk
server.tool(
  "restore_risk",
  "Restore a soft-deleted risk (clears deleted_at timestamp).",
  {
    risk_id: z
      .number()
      .int()
      .positive()
      .describe("Risk ID to restore from soft-delete"),
    env: EnvSchema,
  },
  async ({ risk_id, env }) => {
    const client = await getDbClient(env, { readOnly: false });
    try {
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              { restored: true, ...result.rows[0] },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: add_risk_comment
server.tool(
  "add_risk_comment",
  "Add a comment to a risk. Comments are immutable once created.",
  {
    risk_id: z
      .number()
      .int()
      .positive()
      .describe("Risk ID to comment on"),
    content: z.string().min(1).describe("Comment text"),
    env: EnvSchema,
  },
  async ({ risk_id, content, env }) => {
    const client = await getDbClient(env, { readOnly: false });
    try {
      // Verify risk exists
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              { created: true, comment: result.rows[0] },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: delete_risk_comment
server.tool(
  "delete_risk_comment",
  "Soft-delete a comment on a risk (sets deleted_at timestamp).",
  {
    comment_id: z.number().int().positive().describe("Comment ID to delete"),
    env: EnvSchema,
  },
  async ({ comment_id, env }) => {
    const client = await getDbClient(env, { readOnly: false });
    try {
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ deleted: true, ...result.rows[0] }, null, 2),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: risk_dashboard
server.tool(
  "risk_dashboard",
  "Get a summary dashboard of the risk register: total counts, breakdown by severity and status, top risks by score, and recent activity.",
  {
    env: EnvSchema,
  },
  async ({ env }) => {
    const client = await getDbClient(env);
    try {
      // Total counts
      const totals = await client.query(
        `SELECT
           COUNT(*) FILTER (WHERE deleted_at IS NULL) AS active_risks,
           COUNT(*) FILTER (WHERE deleted_at IS NOT NULL) AS deleted_risks
         FROM ${RISK_TABLES.risk}`
      );

      // By severity
      const bySeverity = await client.query(
        `SELECT severity, COUNT(*) AS count
         FROM ${RISK_TABLES.risk}
         WHERE deleted_at IS NULL
         GROUP BY severity
         ORDER BY CASE severity
           WHEN 'critical' THEN 1 WHEN 'high' THEN 2
           WHEN 'medium' THEN 3 WHEN 'low' THEN 4 END`
      );

      // By status
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

      // Top risks by score
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

      // Recent audit activity
      const recentAudit = await client.query(
        `SELECT al.action, al.entity_type, al.entity_id,
                al.timestamp, al.context
         FROM ${RISK_TABLES.audit_log} al
         ORDER BY al.timestamp DESC
         LIMIT 10`
      );

      const output = {
        totals: totals.rows[0],
        by_severity: bySeverity.rows,
        by_status: byStatus.rows,
        top_risks_by_score: topRisks.rows,
        recent_activity: recentAudit.rows,
      };

      return {
        content: [{ type: "text", text: JSON.stringify(output, null, 2) }],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: risk_matrix
server.tool(
  "risk_matrix",
  "Get a 5x5 risk matrix (likelihood vs impact). Each cell shows the count of risks and their titles. Useful for visualizing risk distribution.",
  {
    env: EnvSchema,
  },
  async ({ env }) => {
    const client = await getDbClient(env);
    try {
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

      // Build the 5x5 matrix
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

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              {
                description:
                  "5x5 risk matrix. Outer key = likelihood (1-5), inner key = impact (1-5). Score = likelihood × impact.",
                matrix,
              },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Tool: risk_audit_log
server.tool(
  "risk_audit_log",
  "Get the audit history for a specific risk, showing all state changes with timestamps, actions, and before/after state snapshots.",
  {
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
  async ({ risk_id, limit, env }) => {
    const client = await getDbClient(env);
    try {
      const result = await client.query(
        `SELECT action, actor_type, actor_id,
                timestamp, previous_state, new_state, context
         FROM ${RISK_TABLES.audit_log}
         WHERE entity_type = 'risk' AND entity_id = $1
         ORDER BY timestamp DESC
         LIMIT $2`,
        [risk_id, limit]
      );

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(
              {
                risk_id,
                entry_count: result.rowCount,
                entries: result.rows,
              },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    } finally {
      await client.end();
    }
  }
);

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);

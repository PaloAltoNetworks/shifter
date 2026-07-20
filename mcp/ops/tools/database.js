// Database inspection and query tools for the shifter-ops MCP server.
//
// These handlers build their MCP `content` responses inline (rather
// than via ok/err) to preserve the exact custom error envelopes for
// the read-only-guard and query/execute error paths.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function.

import { z } from "zod";
import { registerTool } from "../policy.js";
import { getServiceLayer, FORBIDDEN_PATTERN } from "../lib.js";
import { EnvSchema } from "../schemas.js";

function listTablesTool({ withClient }) {
  return {
    name: "list_tables",
    klass: "db_arbitrary",
    description:
      "List all database tables with their service layer and row counts",
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
  };
}

function describeTableTool({ withClient }) {
  return {
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
  };
}

function queryTool({ withClient }) {
  return {
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
  };
}

function executeTool({ withClient }) {
  return {
    name: "execute",
    klass: "db_arbitrary",
    untrusted_inputs: ["sql"],
    is_write: true,
    description:
      "Execute a write SQL statement (UPDATE, INSERT, DELETE) against the Shifter database",
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
  };
}

export function registerDatabaseTools(ctx, deps) {
  registerTool(ctx, listTablesTool(deps));
  registerTool(ctx, describeTableTool(deps));
  registerTool(ctx, queryTool(deps));
  registerTool(ctx, executeTool(deps));
}

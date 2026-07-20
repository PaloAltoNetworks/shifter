// Risk Register read + observability tool factories for the
// shifter-ops MCP server. Registration order and wiring live in
// ../risk.js; these are pure descriptor builders.

import { z } from "zod";
import { ok, err } from "../../respond.js";
import { RISK_TABLES } from "../../lib.js";
import { EnvSchema, SeveritySchema, StatusSchema } from "../../schemas.js";

export function listRisksTool({ withClient }) {
  return {
    name: "list_risks",
    klass: "named_db_read",
    description:
      "List risk register entries. Returns active (non-deleted) risks by default, with computed risk_score and comment_count. Use filters to narrow results.",
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
  };
}

export function getRiskTool({ withClient }) {
  return {
    name: "get_risk",
    klass: "named_db_read",
    description:
      "Get a single risk by ID with full details, including all comments and recent audit history.",
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
  };
}

export function riskDashboardTool({ withClient }) {
  return {
    name: "risk_dashboard",
    klass: "observability",
    description:
      "Get a summary dashboard of the risk register: total counts, breakdown by severity and status, top risks by score, and recent activity.",
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
  };
}

export function riskMatrixTool({ withClient }) {
  return {
    name: "risk_matrix",
    klass: "observability",
    description:
      "Get a 5x5 risk matrix (likelihood vs impact). Each cell shows the count of risks and their titles. Useful for visualizing risk distribution.",
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
  };
}

export function riskAuditLogTool({ withClient }) {
  return {
    name: "risk_audit_log",
    klass: "named_db_read",
    description:
      "Get the audit history for a specific risk, showing all state changes with timestamps, actions, and before/after state snapshots.",
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
  };
}

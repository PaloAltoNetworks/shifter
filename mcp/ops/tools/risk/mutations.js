// Risk Register write tool factories (create / update / delete /
// restore) for the shifter-ops MCP server. Registration order and
// wiring live in ../risk.js; these are pure descriptor builders.
//
// update_risk keeps its handler as a separate top-level function so
// neither the factory (which carries the large schema) nor the handler
// exceeds the per-function length budget.

import { z } from "zod";
import { ok, err } from "../../respond.js";
import { RISK_TABLES, buildUpdateSet } from "../../lib.js";
import {
  EnvSchema,
  SeveritySchema,
  StatusSchema,
  StrideSchema,
  ScoreSchema,
} from "../../schemas.js";

export function createRiskTool({ withClient }) {
  return {
    name: "create_risk",
    klass: "named_db_write",
    description:
      "Create a new risk register entry. Only title and description are required; all other fields have sensible defaults.",
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
  };
}

const UPDATE_RISK_SCHEMA = {
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
};

async function updateRiskHandler({ withClient }, args) {
  const {
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
  } = args;

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
}

export function updateRiskTool(deps) {
  return {
    name: "update_risk",
    klass: "named_db_write",
    description:
      "Update one or more fields on an existing risk. Only provide the fields you want to change. Returns the full updated risk.",
    schema: UPDATE_RISK_SCHEMA,
    handler: (args) => updateRiskHandler(deps, args),
  };
}

export function deleteRiskTool({ withClient }) {
  return {
    name: "delete_risk",
    klass: "named_db_write",
    description:
      "Soft-delete a risk (sets deleted_at timestamp). The risk can be restored later with restore_risk.",
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
  };
}

export function restoreRiskTool({ withClient }) {
  return {
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
  };
}

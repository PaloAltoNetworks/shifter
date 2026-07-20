// Risk Register comment tool factories for the shifter-ops MCP server.
// Registration order and wiring live in ../risk.js; these are pure
// descriptor builders.

import { z } from "zod";
import { ok, err } from "../../respond.js";
import { RISK_TABLES } from "../../lib.js";
import { EnvSchema } from "../../schemas.js";

export function addRiskCommentTool({ withClient }) {
  return {
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
  };
}

export function deleteRiskCommentTool({ withClient }) {
  return {
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
  };
}

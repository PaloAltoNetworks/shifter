// Range reconciliation and range/subnet query tools for the
// shifter-ops MCP server. Orphan classification lives in reconcile.js
// (injected via deps) so it can be unit-tested with a fake client.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function. reconcile_ranges keeps its
// handler as a separate top-level function so neither the factory nor
// the handler exceeds the per-function length budget.

import { z } from "zod";
import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { EnvSchema, CMD_DESCRIBE_INSTANCES } from "../schemas.js";

async function reconcileRangesHandler(deps, { env, execute: shouldExecute }) {
  const {
    getProfile,
    aws,
    withClient,
    findOrphanedInstances,
    terminateOrphans,
    markOrphansDestroyedInDb,
  } = deps;
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
      CMD_DESCRIBE_INSTANCES,
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

    const orphans = await withClient(env, { readOnly: true }, (client) =>
      findOrphanedInstances(client, runningEc2s, ec2Ids)
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
    const terminated = terminateOrphans(profile, orphans);

    await withClient(env, { readOnly: false }, (client) =>
      markOrphansDestroyedInDb(client, orphans)
    );

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
        ranges: new Set(
          orphans.filter((o) => o.range_id).map((o) => o.range_id)
        ).size,
      },
    };
    return ok(JSON.stringify(report, null, 2));
  } catch (e) {
    return err(e);
  }
}

function reconcileRangesTool(deps) {
  return {
    name: "reconcile_ranges",
    klass: "infra_mutation",
    description:
      "Find orphaned EC2 range instances (running in AWS but belonging to failed/destroyed ranges). Dry-run by default; set execute=true to terminate and update DB.",
    schema: {
      env: EnvSchema,
      execute: z
        .boolean()
        .default(false)
        .describe(
          "Set to true to actually terminate instances and update DB. Default is dry-run."
        ),
    },
    handler: (args) => reconcileRangesHandler(deps, args),
  };
}

function listRangesTool({ withClient }) {
  return {
    name: "list_ranges",
    klass: "named_db_read",
    description:
      "List ranges with status, user, scenario, instance count, and timestamps. Useful for checking active/failed/destroyed ranges.",
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
  };
}

function getRangeTool({ withClient }) {
  return {
    name: "get_range",
    klass: "named_db_read",
    description:
      "Get detailed info for a single range including instances and subnet allocations.",
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
  };
}

function listSubnetAllocationsTool({ withClient }) {
  return {
    name: "list_subnet_allocations",
    klass: "named_db_read",
    description:
      "List subnet CIDR allocations. Useful for debugging race conditions and stale reservations.",
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
  };
}

export function registerRangesTools(ctx, deps) {
  registerTool(ctx, reconcileRangesTool(deps));
  registerTool(ctx, listRangesTool(deps));
  registerTool(ctx, getRangeTool(deps));
  registerTool(ctx, listSubnetAllocationsTool(deps));
}

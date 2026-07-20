// Range-reconciliation DB helpers for the shifter-ops MCP server.
//
// These classify running range EC2 instances against the Mission
// Control / Engine tables to find orphans (running in AWS but belonging
// to a failed/destroyed range, or with no matching range at all), then
// terminate and soft-delete them. Extracted from index.js during the
// #690 modularization so the classification logic has focused,
// fake-client tests (reconcile.test.js) independent of MCP bootstrap.
//
// All functions take an explicit `client` (pg) or `profile`; they hold
// no module state.

import { aws } from "./aws.js";
import { ARG_INSTANCE_IDS } from "./schemas.js";

// Resolve an orphan record for a running EC2 with no engine_instance match,
// using its shifter:range_id tag. Returns null when the range is still active.
export async function resolveOrphanByRangeTag(client, ec2) {
  const parsedRangeId = ec2.RangeId ? Number.parseInt(ec2.RangeId, 10) : null;
  const rangeResult = await client.query(
    `SELECT mcr.id AS range_id, mcr.status AS range_status,
            mcr.request_id AS engine_request_id
     FROM mission_control_range mcr
     WHERE mcr.id = $1`,
    [parsedRangeId]
  );

  if (rangeResult.rows.length === 0) {
    // Range not found in DB at all - still an orphan EC2
    return {
      ec2_id: ec2.InstanceId,
      ec2_name: ec2.Name,
      reason: `no aws_instance_id match; range ${parsedRangeId} not found in DB`,
      engine_instance_id: null,
      engine_request_id: null,
      range_id: null,
    };
  }

  const range = rangeResult.rows[0];

  // Only flag as orphan if range is in a terminal state
  if (range.range_status !== "failed" && range.range_status !== "destroyed") {
    return null;
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

  return {
    ec2_id: ec2.InstanceId,
    ec2_name: ec2.Name,
    reason: `no aws_instance_id match; range ${parsedRangeId} status: ${range.range_status}`,
    engine_instance_id: null,
    engine_instance_ids: eiResult.rows.map((r) => r.engine_instance_id),
    engine_request_id: range.engine_request_id,
    range_id: range.range_id,
    range_status: range.range_status,
  };
}

// Classify an EC2 that DID match an engine_instance row (via LEFT JOIN).
// Returns an orphan record, or null when the range is healthy.
export function classifyMatchedOrphan(ec2, db) {
  if (db.range_status == null) {
    // LEFT JOIN found engine_instance but no matching range — orphan
    return {
      ec2_id: ec2.InstanceId,
      ec2_name: ec2.Name,
      reason: "engine_instance exists but no associated range found",
      engine_instance_id: db.engine_instance_id,
      engine_request_id: db.engine_request_id,
      range_id: null,
      instance_status: db.instance_status,
      role: db.role,
    };
  }
  if (db.range_status === "failed" || db.range_status === "destroyed") {
    return {
      ec2_id: ec2.InstanceId,
      ec2_name: ec2.Name,
      reason: `range status: ${db.range_status}`,
      engine_instance_id: db.engine_instance_id,
      engine_request_id: db.engine_request_id,
      range_id: db.range_id,
      instance_status: db.instance_status,
      role: db.role,
    };
  }
  return null;
}

// Query DB for engine_instances matching the running EC2 IDs and return the
// orphan records (instances whose range is missing or in a terminal state).
export async function findOrphanedInstances(client, runningEc2s, ec2Ids) {
  const placeholders = ec2Ids.map((_, i) => `$${i + 1}`).join(", ");
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
    const orphan = db
      ? classifyMatchedOrphan(ec2, db)
      : await resolveOrphanByRangeTag(client, ec2);
    if (orphan) {
      found.push(orphan);
    }
  }
  return found;
}

// Terminate the orphaned EC2 instances and return per-instance termination state.
// `awsFn` defaults to the real argv-array AWS runner; tests inject a fake
// (the same default-arg DI convention lib.js uses for ghExec/resolveGitRef).
export function terminateOrphans(profile, orphans, awsFn = aws) {
  const terminated = [];
  for (const orphan of orphans) {
    const termResult = awsFn(profile, [
      "ec2",
      "terminate-instances",
      ARG_INSTANCE_IDS,
      orphan.ec2_id,
    ]);
    const state = termResult.TerminatingInstances?.[0]?.CurrentState?.Name;
    terminated.push({ ec2_id: orphan.ec2_id, state });
  }
  return terminated;
}

// Soft-delete the engine_instances, ranges, requests, and range instances
// associated with the terminated orphans.
export async function markOrphansDestroyedInDb(client, orphans) {
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
    ...new Set(orphans.filter((o) => o.range_id).map((o) => o.range_id)),
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
      orphans.filter((o) => o.engine_request_id).map((o) => o.engine_request_id)
    ),
  ];
  if (engineRequestIds.length > 0) {
    const ph = engineRequestIds.map((_, i) => `$${i + 1}`).join(", ");
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
}

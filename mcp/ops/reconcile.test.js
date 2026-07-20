// Focused, fixture-based tests for the range-reconciliation helpers
// (issue #690). These exercise the orphan-classification logic in
// isolation — no MCP server, no policy load, no real pg/aws — using a
// single fake-client fixture rather than per-assertion inline mocks
// (which OOM in this suite; see CLAUDE.md "Avoid Micro-Tests").

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  classifyMatchedOrphan,
  resolveOrphanByRangeTag,
  findOrphanedInstances,
  terminateOrphans,
  markOrphansDestroyedInDb,
} from "./reconcile.js";

// Fake pg client: `responder(sql, params)` returns the rows for each
// query; every call is recorded on `.calls` for assertion.
function fakeClient(responder) {
  const calls = [];
  return {
    calls,
    async query(sql, params) {
      calls.push({ sql, params });
      const rows = responder(sql, params) ?? [];
      return { rows, rowCount: rows.length };
    },
  };
}

describe("classifyMatchedOrphan", () => {
  const ec2 = { InstanceId: "i-0abc", Name: "range-1-kali" };

  it("flags an engine_instance with no associated range", () => {
    const orphan = classifyMatchedOrphan(ec2, {
      range_status: null,
      engine_instance_id: 42,
      engine_request_id: 7,
      instance_status: "running",
      role: "kali",
    });
    assert.equal(orphan.ec2_id, "i-0abc");
    assert.equal(orphan.reason, "engine_instance exists but no associated range found");
    assert.equal(orphan.engine_instance_id, 42);
    assert.equal(orphan.range_id, null);
  });

  it("flags an engine_instance whose range is failed or destroyed", () => {
    for (const status of ["failed", "destroyed"]) {
      const orphan = classifyMatchedOrphan(ec2, {
        range_status: status,
        engine_instance_id: 1,
        engine_request_id: 2,
        range_id: 9,
        instance_status: "running",
        role: "victim",
      });
      assert.equal(orphan.reason, `range status: ${status}`);
      assert.equal(orphan.range_id, 9);
    }
  });

  it("returns null when the range is healthy", () => {
    assert.equal(
      classifyMatchedOrphan(ec2, {
        range_status: "ready",
        engine_instance_id: 1,
        engine_request_id: 2,
        range_id: 9,
      }),
      null
    );
  });
});

describe("resolveOrphanByRangeTag", () => {
  const ec2 = { InstanceId: "i-0def", Name: "range-5-victim", RangeId: "5" };

  it("flags a running EC2 whose range row is absent from the DB", async () => {
    const client = fakeClient(() => []); // range lookup returns nothing
    const orphan = await resolveOrphanByRangeTag(client, ec2);
    assert.equal(orphan.ec2_id, "i-0def");
    assert.match(orphan.reason, /range 5 not found in DB/);
    assert.equal(orphan.range_id, null);
    assert.equal(orphan.engine_instance_id, null);
  });

  it("returns null when the tagged range is still active", async () => {
    const client = fakeClient(() => [
      { range_id: 5, range_status: "ready", engine_request_id: 30 },
    ]);
    assert.equal(await resolveOrphanByRangeTag(client, ec2), null);
  });

  it("collects pending engine_instances for a terminal range", async () => {
    const client = fakeClient((sql) => {
      if (sql.includes("FROM mission_control_range")) {
        return [{ range_id: 5, range_status: "failed", engine_request_id: 30 }];
      }
      if (sql.includes("FROM engine_instance")) {
        return [
          { engine_instance_id: 100, status: "pending", role: "kali" },
          { engine_instance_id: 101, status: "pending", role: "victim" },
        ];
      }
      return [];
    });
    const orphan = await resolveOrphanByRangeTag(client, ec2);
    assert.equal(orphan.range_status, "failed");
    assert.deepEqual(orphan.engine_instance_ids, [100, 101]);
    assert.equal(orphan.engine_request_id, 30);
  });

  it("returns empty engine_instance_ids for a terminal range with no request id", async () => {
    const client = fakeClient(() => [
      { range_id: 5, range_status: "destroyed", engine_request_id: null },
    ]);
    const orphan = await resolveOrphanByRangeTag(client, ec2);
    assert.deepEqual(orphan.engine_instance_ids, []);
  });
});

describe("findOrphanedInstances", () => {
  it("classifies matched EC2s via the LEFT JOIN and unmatched via the range tag", async () => {
    const runningEc2s = [
      { InstanceId: "i-match-fail", Name: "r1", RangeId: "1" },
      { InstanceId: "i-match-ok", Name: "r2", RangeId: "2" },
      { InstanceId: "i-unmatched", Name: "r3", RangeId: "3" },
    ];
    const ec2Ids = runningEc2s.map((e) => e.InstanceId);

    const client = fakeClient((sql) => {
      // First query: the engine_instance LEFT JOIN mission_control_range.
      if (sql.includes("LEFT JOIN mission_control_range")) {
        return [
          {
            engine_instance_id: 11,
            instance_status: "running",
            ec2_id: "i-match-fail",
            role: "kali",
            engine_request_id: 71,
            range_id: 1,
            range_status: "failed",
          },
          {
            engine_instance_id: 12,
            instance_status: "running",
            ec2_id: "i-match-ok",
            role: "victim",
            engine_request_id: 72,
            range_id: 2,
            range_status: "ready",
          },
        ];
      }
      // resolveOrphanByRangeTag path for i-unmatched (RangeId 3).
      if (sql.includes("FROM mission_control_range")) {
        return [{ range_id: 3, range_status: "destroyed", engine_request_id: null }];
      }
      return [];
    });

    const orphans = await findOrphanedInstances(client, runningEc2s, ec2Ids);
    const ids = orphans.map((o) => o.ec2_id).sort();
    // i-match-ok (healthy range) is excluded; the other two are orphans.
    assert.deepEqual(ids, ["i-match-fail", "i-unmatched"]);
  });
});

describe("terminateOrphans", () => {
  it("terminates each orphan and returns its post-termination state", () => {
    const calls = [];
    const fakeAws = (profile, args) => {
      calls.push({ profile, args });
      return {
        TerminatingInstances: [{ CurrentState: { Name: "shutting-down" } }],
      };
    };
    const orphans = [{ ec2_id: "i-1" }, { ec2_id: "i-2" }];
    const result = terminateOrphans("dev-profile", orphans, fakeAws);
    assert.deepEqual(result, [
      { ec2_id: "i-1", state: "shutting-down" },
      { ec2_id: "i-2", state: "shutting-down" },
    ]);
    assert.equal(calls.length, 2);
    // Verify EVERY iteration's argv, not just the first — a
    // loop-variable-capture bug that reused i-1's id on the second call
    // would otherwise slip through (the result array is built from
    // orphan.ec2_id, and the fake returns a fixed state regardless of input).
    assert.deepEqual(calls[0].args, [
      "ec2",
      "terminate-instances",
      "--instance-ids",
      "i-1",
    ]);
    assert.deepEqual(calls[1].args, [
      "ec2",
      "terminate-instances",
      "--instance-ids",
      "i-2",
    ]);
  });
});

describe("markOrphansDestroyedInDb", () => {
  it("soft-deletes engine_instances, ranges, and associated requests", async () => {
    const client = fakeClient(() => []);
    const orphans = [
      {
        ec2_id: "i-1",
        engine_instance_id: 11,
        range_id: 1,
        engine_request_id: 71,
      },
      {
        ec2_id: "i-2",
        engine_instance_ids: [12, 13],
        range_id: 2,
        engine_request_id: 72,
      },
    ];

    await markOrphansDestroyedInDb(client, orphans);

    const engineUpdate = client.calls.find((c) =>
      c.sql.includes("UPDATE engine_instance")
    );
    assert.ok(engineUpdate, "engine_instance UPDATE issued");
    assert.deepEqual(engineUpdate.params.sort(), [11, 12, 13]);

    const rangeUpdate = client.calls.find((c) =>
      c.sql.includes("UPDATE mission_control_range")
    );
    assert.ok(rangeUpdate, "range UPDATE issued");
    assert.deepEqual(rangeUpdate.params.sort(), [1, 2]);

    const requestUpdate = client.calls.find((c) =>
      c.sql.includes("UPDATE cms_request")
    );
    assert.ok(requestUpdate, "cms_request UPDATE issued");
    assert.deepEqual(requestUpdate.params.sort(), [71, 72]);

    const rangeInstanceUpdate = client.calls.find((c) =>
      c.sql.includes("UPDATE cms_rangeinstance")
    );
    assert.ok(rangeInstanceUpdate, "cms_rangeinstance UPDATE issued");
    assert.deepEqual(rangeInstanceUpdate.params.sort(), [71, 72]);
  });

  it("no-ops cleanly when there is nothing to soft-delete", async () => {
    const client = fakeClient(() => []);
    await markOrphansDestroyedInDb(client, [{ ec2_id: "i-x" }]);
    assert.equal(client.calls.length, 0);
  });
});

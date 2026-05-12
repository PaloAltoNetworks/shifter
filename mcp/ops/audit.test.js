// Tests for the per-call JSONL audit log (#1198 Phase 2).
//
// The audit module is side-effect-free except for a single append
// per call. These tests use a per-test tmpdir audit path so they
// don't touch the real ~/.shifter-ops-audit.jsonl.

import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  readFileSync,
  existsSync,
  rmSync,
  chmodSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  resolveAuditPath,
  sanitizeArgs,
  appendAuditRecord,
} from "./audit.js";

function makeFakePolicy({ enabled = true, path, redact = [] } = {}) {
  return {
    auditConfig() {
      return { enabled, path, redact };
    },
  };
}

describe("resolveAuditPath", () => {
  it("expands a leading ~/ to the user's home directory", () => {
    const out = resolveAuditPath("~/.shifter-ops-audit.jsonl");
    assert.notEqual(out[0], "~", "tilde should be expanded");
    assert.ok(out.endsWith(".shifter-ops-audit.jsonl"));
  });

  it("expands a bare ~ to the user's home directory", () => {
    const out = resolveAuditPath("~");
    assert.notEqual(out, "~");
  });

  it("returns an absolute path unchanged", () => {
    const out = resolveAuditPath("/var/log/audit.jsonl");
    assert.equal(out, "/var/log/audit.jsonl");
  });

  it("throws on empty / non-string", () => {
    assert.throws(() => resolveAuditPath(""), TypeError);
    assert.throws(() => resolveAuditPath(null), TypeError);
    assert.throws(() => resolveAuditPath(undefined), TypeError);
  });
});

describe("sanitizeArgs", () => {
  it("redacts top-level keys in the redact list", () => {
    const out = sanitizeArgs(
      { user: "alice", password: "p", note: "n" },
      ["password"],
    );
    assert.deepEqual(out, {
      user: "alice",
      password: "<redacted>",
      note: "n",
    });
  });

  it("recurses into nested objects", () => {
    const out = sanitizeArgs(
      { creds: { username: "u", password: "p" }, env: "dev" },
      ["password"],
    );
    assert.deepEqual(out.creds, { username: "u", password: "<redacted>" });
    assert.equal(out.env, "dev");
  });

  it("recurses into arrays of objects", () => {
    const out = sanitizeArgs(
      { entries: [{ password: "a" }, { password: "b" }] },
      ["password"],
    );
    assert.deepEqual(out.entries, [
      { password: "<redacted>" },
      { password: "<redacted>" },
    ]);
  });

  it("does not mutate the input", () => {
    const input = { password: "raw" };
    sanitizeArgs(input, ["password"]);
    assert.equal(input.password, "raw");
  });

  it("returns the value unchanged when there is no redact list", () => {
    const input = { password: "p" };
    const out = sanitizeArgs(input, []);
    // Even with an empty explicit redact list, the suffix-based
    // classifier still catches keys ending in `_password` etc.
    // (codex review #1180 cycle 1 finding 9). `password` exactly
    // matches the suffix `_password` only via the explicit allowlist
    // path; with an empty list the bare `password` key passes
    // through.
    assert.deepEqual(out, { password: "p" });
  });

  it("redact list lookup is case-insensitive", () => {
    const out = sanitizeArgs(
      { DB_PASSWORD: "supersecret", db_password: "alsosecret", db_user: "u" },
      ["db_password"],
    );
    assert.equal(out.DB_PASSWORD, "<redacted>");
    assert.equal(out.db_password, "<redacted>");
    assert.equal(out.db_user, "u");
  });

  it("suffix-based deny-by-default catches sensitive-shaped keys", () => {
    const out = sanitizeArgs(
      {
        DB_PASSWORD: "p",
        ROOT_PASSPHRASE: "x",
        MY_API_TOKEN: "t",
        JWT_SECRET: "j",
        RSA_PRIVATE_KEY: "k",
        DB_USER: "u", // not a secret suffix
        REGION: "us-east-2",
      },
      [], // explicit list empty — suffix classifier alone must catch
    );
    assert.equal(out.DB_PASSWORD, "<redacted>");
    assert.equal(out.ROOT_PASSPHRASE, "<redacted>");
    assert.equal(out.MY_API_TOKEN, "<redacted>");
    assert.equal(out.JWT_SECRET, "<redacted>");
    assert.equal(out.RSA_PRIVATE_KEY, "<redacted>");
    assert.equal(out.DB_USER, "u");
    assert.equal(out.REGION, "us-east-2");
  });

  it("pointer suffix wins over sensitive suffix", () => {
    const out = sanitizeArgs(
      { MY_DB_SECRET_ID: "projects/x/secrets/y", FIELD_ENCRYPTION_KEY_NAME: "n" },
      [],
    );
    // Both end in pointer suffixes (`_ID`, `_NAME`) so they are
    // identifiers, not secret material.
    assert.equal(out.MY_DB_SECRET_ID, "projects/x/secrets/y");
    assert.equal(out.FIELD_ENCRYPTION_KEY_NAME, "n");
  });

  it("passes null / undefined / primitives through", () => {
    assert.equal(sanitizeArgs(null, ["x"]), null);
    assert.equal(sanitizeArgs(undefined, ["x"]), undefined);
    assert.equal(sanitizeArgs(42, ["x"]), 42);
    assert.equal(sanitizeArgs("str", ["x"]), "str");
  });
});

describe("appendAuditRecord", () => {
  let dir;
  let auditPath;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "mcp-ops-audit-test-"));
    auditPath = join(dir, "audit.jsonl");
  });

  afterEach(() => {
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch {
      // tmpdir cleanup is best-effort.
    }
  });

  it("appends one JSONL line per call with sanitized args", () => {
    const policy = makeFakePolicy({
      path: auditPath,
      redact: ["password"],
    });

    appendAuditRecord(policy, {
      timestamp: "2026-05-12T20:00:00Z",
      tool: "query",
      class: "named_db_read",
      env: "dev",
      profile: "standard",
      args: { sql: "select 1", password: "should-not-appear" },
      result_class: "success",
      duration_ms: 42,
    });
    appendAuditRecord(policy, {
      timestamp: "2026-05-12T20:00:01Z",
      tool: "query",
      class: "named_db_read",
      env: "dev",
      profile: "standard",
      args: { sql: "select 2" },
      result_class: "success",
      duration_ms: 11,
    });

    const lines = readFileSync(auditPath, "utf-8").trim().split("\n");
    assert.equal(lines.length, 2);

    const r1 = JSON.parse(lines[0]);
    assert.equal(r1.tool, "query");
    assert.equal(r1.sanitized_args.sql, "select 1");
    assert.equal(r1.sanitized_args.password, "<redacted>");
    assert.equal(r1.args, undefined, "raw args must not land on disk");
    assert.equal(r1.result_class, "success");
    assert.equal(r1.duration_ms, 42);

    const r2 = JSON.parse(lines[1]);
    assert.equal(r2.sanitized_args.sql, "select 2");
  });

  it("does not write when audit is disabled", () => {
    const policy = makeFakePolicy({
      enabled: false,
      path: auditPath,
      redact: [],
    });

    const result = appendAuditRecord(policy, {
      timestamp: "t",
      tool: "x",
      class: "observability",
      args: {},
      result_class: "success",
      duration_ms: 1,
    });

    assert.equal(result.ok, false);
    assert.equal(result.error, "audit-disabled");
    assert.equal(existsSync(auditPath), false);
  });

  it("creates the parent directory if missing", () => {
    const nestedPath = join(dir, "nested", "deep", "audit.jsonl");
    const policy = makeFakePolicy({ path: nestedPath, redact: [] });

    appendAuditRecord(policy, {
      timestamp: "t",
      tool: "x",
      class: "observability",
      args: {},
      result_class: "success",
      duration_ms: 1,
    });

    assert.ok(existsSync(nestedPath));
  });

  it("returns ok=false and does not throw when the path is unwritable", () => {
    // Drop write permission on the dir so appendFileSync fails. The
    // call must not throw out to the caller — the tool response would
    // be lost otherwise.
    chmodSync(dir, 0o500);
    try {
      const policy = makeFakePolicy({ path: auditPath, redact: [] });
      const result = appendAuditRecord(policy, {
        timestamp: "t",
        tool: "x",
        class: "observability",
        args: {},
        result_class: "success",
        duration_ms: 1,
      });
      assert.equal(result.ok, false);
      assert.ok(typeof result.error === "string");
    } finally {
      // Restore so afterEach can clean up.
      chmodSync(dir, 0o700);
    }
  });

  it("throws TypeError on a malformed policy fixture (defensive)", () => {
    assert.throws(() => appendAuditRecord({}, { tool: "x" }), TypeError);
    assert.throws(() => appendAuditRecord(null, { tool: "x" }), TypeError);
  });

  it("creates the audit file with owner-only (0600) permissions", () => {
    const policy = makeFakePolicy({ path: auditPath, redact: [] });
    appendAuditRecord(policy, {
      timestamp: "t",
      tool: "x",
      class: "observability",
      args: {},
      result_class: "success",
      duration_ms: 1,
    });
    const mode = statSync(auditPath).mode & 0o777;
    assert.equal(
      mode,
      0o600,
      `expected 0o600 (owner-only) audit file mode, got 0o${mode.toString(8)}`,
    );
  });

  it("tightens a pre-existing audit file's permissions on first append", () => {
    // Simulate a legacy run that left the file world-readable.
    writeFileSync(auditPath, "");
    chmodSync(auditPath, 0o644);
    const policy = makeFakePolicy({ path: auditPath, redact: [] });
    appendAuditRecord(policy, {
      timestamp: "t",
      tool: "x",
      class: "observability",
      args: {},
      result_class: "success",
      duration_ms: 1,
    });
    const mode = statSync(auditPath).mode & 0o777;
    assert.equal(mode, 0o600);
  });
});

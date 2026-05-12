// Append-only JSONL audit log for the shifter-ops MCP server (#1198,
// Phase 2 of #777). One line per tool invocation. Side-effect-free
// helpers are exported so tests can drive them with a synthetic
// policy fixture; the real-life writer is `appendAuditRecord`,
// invoked from the registerTool wrapper after every call.
//
// Failure mode: audit writes are best-effort. The MCP server must
// continue serving even if the audit file is unwritable (read-only
// dir, missing dir, full disk). Errors land on `console.error` and
// the original tool response is preserved.

import {
  chmodSync,
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  statSync,
  writeSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname } from "node:path";

const REDACTED_TOKEN = "<redacted>";

// File-permission targets for the audit log. The log records every
// tool invocation's arguments (SQL text, env names, idempotency
// keys, and any fields missed by redaction) — a local-user attacker
// who reads it sees the full operational history. 0600 makes the
// file owner-only; 0700 makes the parent directory owner-only so a
// new audit file inherits a non-traversable parent. Codex review
// #1180 cycle 1 finding 8.
const AUDIT_FILE_MODE = 0o600;
const AUDIT_DIR_MODE = 0o700;

// Suffix-based deny-by-default for argument names that look like
// secret material. Mirrors the Python classifier at
// shifter/shifter_platform/shared/cloud/sensitive_env.py so the
// audit redaction has the same shape on both sides of the platform.
// Pointer suffixes win over sensitive suffixes: an argument named
// `MY_DB_SECRET_ID` is an identifier (a Secret Manager *id*) and is
// NOT redacted. Codex review #1180 cycle 1 finding 9.
const SENSITIVE_SUFFIXES = [
  "_password",
  "_passphrase",
  "_private_key",
  "_api_token",
  "_credential",
  "_credentials",
  "_secret",
];
const POINTER_SUFFIXES = [
  "_id",
  "_ref",
  "_arn",
  "_name",
  "_url",
  "_file",
  "_path",
  "_bucket",
  "_host",
  "_port",
];

function _isKeyRedactable(key, lowerCaseSet) {
  const lower = key.toLowerCase();
  // Explicit allowlist hit (case-insensitive) → redact.
  if (lowerCaseSet.has(lower)) return true;
  // Pointer suffixes always win over sensitive ones — an `_id`
  // suffix is an identifier, not the secret material.
  for (const suffix of POINTER_SUFFIXES) {
    if (lower.endsWith(suffix)) return false;
  }
  for (const suffix of SENSITIVE_SUFFIXES) {
    if (lower.endsWith(suffix)) return true;
  }
  return false;
}

/**
 * Resolve a `~/`-prefixed path against the current user's home
 * directory. Anything else passes through. Symmetric to the
 * .shifter.yaml convention (`audit.path: ~/.shifter-ops-audit.jsonl`).
 */
export function resolveAuditPath(rawPath) {
  if (typeof rawPath !== "string" || rawPath.length === 0) {
    throw new TypeError("resolveAuditPath: path must be a non-empty string");
  }
  if (rawPath === "~") return homedir();
  if (rawPath.startsWith("~/")) return rawPath.replace("~", homedir());
  return rawPath;
}

/**
 * Walk `args` and replace any value at a key that the audit policy
 * considers sensitive with `"<redacted>"`. The policy is:
 *
 *   1. An explicit case-insensitive match against `redactList`
 *      entries (from `.shifter.yaml`'s `audit.redact`).
 *   2. A suffix-based deny-by-default classifier (`_password`,
 *      `_passphrase`, `_private_key`, `_api_token`, `_credential`,
 *      `_credentials`, `_secret`). Pointer suffixes (`_id`, `_ref`,
 *      `_arn`, `_name`, `_url`, `_file`, `_path`, `_bucket`, `_host`,
 *      `_port`) take precedence so identifiers like
 *      `DB_SECRET_ID` are correctly classed as non-sensitive.
 *
 * Recurses into nested objects and arrays. Returns a deep-copied
 * structure; the input is never mutated.
 */
export function sanitizeArgs(args, redactList) {
  if (args === null || args === undefined) return args;
  const lowerCaseSet = new Set(
    (redactList ?? []).map((k) => (typeof k === "string" ? k.toLowerCase() : "")),
  );
  return _sanitize(args, lowerCaseSet);
}

function _sanitize(value, lowerCaseSet) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) {
    return value.map((v) => _sanitize(v, lowerCaseSet));
  }
  if (typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      if (_isKeyRedactable(k, lowerCaseSet)) {
        out[k] = REDACTED_TOKEN;
      } else {
        out[k] = _sanitize(v, lowerCaseSet);
      }
    }
    return out;
  }
  return value;
}

/**
 * Append one JSONL audit record. Returns `{ ok: true }` on success
 * or `{ ok: false, error }` on a write failure (best-effort: caller
 * does NOT bubble the error out of the tool call).
 *
 * `policy` provides:
 *   - `auditConfig()` → `{ enabled, path, redact }` from .shifter.yaml
 *
 * `record` shape (caller fills these in):
 *   - timestamp: ISO-8601 string (caller provides; tests inject a
 *     deterministic value)
 *   - tool: string
 *   - class: string
 *   - env: "dev" | "prod" | null
 *   - profile: "read_only" | "standard" | "destructive"
 *   - args: object (raw; sanitized internally before emit)
 *   - result_class: "success" | "error" | "dry_run" | "cached"
 *   - duration_ms: number
 *   - error_class?: string (set when result_class is "error")
 *   - idempotency_key?: string
 *   - plan_id?: string
 */
export function appendAuditRecord(policy, record) {
  if (!policy || typeof policy.auditConfig !== "function") {
    throw new TypeError("appendAuditRecord: policy.auditConfig() is required");
  }
  const audit = policy.auditConfig();
  if (!audit?.enabled) return { ok: false, error: "audit-disabled" };
  if (!record || typeof record !== "object") {
    throw new TypeError("appendAuditRecord: record must be an object");
  }

  const path = resolveAuditPath(audit.path);
  const sanitized_args = sanitizeArgs(record.args, audit.redact ?? []);

  // Build the emit record. The raw `args` must NEVER land on disk;
  // emit `sanitized_args` in its place.
  const emit = { ...record, sanitized_args };
  delete emit.args;

  try {
    mkdirSync(dirname(path), { recursive: true, mode: AUDIT_DIR_MODE });
    // openSync(..., 'a', 0o600) creates the file owner-only when it
    // doesn't already exist, but ignores the mode for an existing
    // file. If a previous process created the file with a looser
    // mode, tighten it here so the contents become owner-only on
    // first append from this version. statSync isolates the legacy-
    // perms branch so the chmod call only runs when needed.
    if (existsSync(path)) {
      try {
        const mode = statSync(path).mode & 0o777;
        if (mode !== AUDIT_FILE_MODE) {
          chmodSync(path, AUDIT_FILE_MODE);
        }
      } catch {
        // Permission tightening is best-effort; fall through to the
        // open + write below, which will surface real failures.
      }
    }
    const fd = openSync(path, "a", AUDIT_FILE_MODE);
    try {
      writeSync(fd, JSON.stringify(emit) + "\n");
    } finally {
      closeSync(fd);
    }
    return { ok: true };
  } catch (err) {
    // Audit failures must not break tool calls.
    console.error(`mcp/ops audit append failed: ${err.message}`);
    return { ok: false, error: err.message };
  }
}

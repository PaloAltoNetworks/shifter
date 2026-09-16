// Untrusted-input fencing for the shifter-ops policy layer (Phase 4,
// #1200): producer source labels, consumer field validation, the
// acknowledgement gate, and the response fence wrap. Split out of
// policy.js (javascript:S104); behavior is unchanged.

import { PolicyError } from "./policy-config.js";

// ===========================================================================
// Phase 4 (#1200): untrusted-input fencing.
//
// Producers (tools whose handler returns free-form text sourced from
// outside the operator's own trust boundary — log streams, S3 object
// bodies, SSM stdout, future web fetches) declare a small static
// source label in their descriptor. The wrapper post-processes the
// handler's text return and embeds it inside an
// `[UNTRUSTED:<source>:BEGIN] ... [UNTRUSTED:<source>:END]` fence so
// the LLM can recognize that subsequent text is attacker-controllable.
//
// Consumers (tools whose handler accepts free-form text that becomes
// the operative payload — `query.sql`, `execute.sql`,
// `ssm_send_command.command`, `run_manage_command.command`) declare
// which fields to scan. The wrapper refuses calls whose declared
// fields contain a fence pattern unless
// `acknowledge_untrusted_input: true` is also set, forcing the agent
// to explicitly acknowledge it is acting on text sourced from a
// producer's untrusted output.
// ===========================================================================

const UNTRUSTED_SOURCE_LABEL_RE = /^[a-z][a-z0-9_]{0,31}$/;
// Match a producer fence opener anywhere in the field. The closer is
// allowed to be missing; an opener alone is enough signal that the
// argument carries content from an untrusted producer.
const UNTRUSTED_FENCE_OPENER_RE = /\[UNTRUSTED:[a-z][a-z0-9_]{0,31}:BEGIN]/;

function _validateUntrustedSource(descriptor, policy) {
  const label = descriptor.untrusted_source;
  if (label === undefined) return;
  if (typeof label !== "string" || !UNTRUSTED_SOURCE_LABEL_RE.test(label)) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' has malformed untrusted_source '${label}' (must match ${UNTRUSTED_SOURCE_LABEL_RE})`,
    );
  }
  const allow = policy.untrustedSources();
  // Allowlist is required: if `.shifter.yaml` omits `untrusted_sources`
  // entirely while a descriptor declares one, the contract collapses
  // to "anything goes" — and a typo in the descriptor (or a malicious
  // future descriptor) could relabel the fence without any check.
  // Force the operator to enumerate accepted labels explicitly.
  if (allow.size === 0) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' declares untrusted_source '${label}' but .shifter.yaml has no 'untrusted_sources' allowlist`,
    );
  }
  if (!allow.has(label)) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' has untrusted_source '${label}' not in .shifter.yaml's untrusted_sources allowlist`,
    );
  }
}

// Codex review #1201 cycle 2 finding: a typo in a descriptor's
// `untrusted_inputs` / `sensitive_args` list (e.g. `["sqll"]` on
// `query`) registers cleanly and silently disables the intended
// guardrail. Cross-check every named field against the registered
// schema's keys so misconfigured descriptors fail closed at startup.
function _assertFieldsInSchema(descriptor, listName) {
  const fields = descriptor[listName];
  if (fields === undefined) return;
  if (!Array.isArray(fields) || fields.some((f) => typeof f !== "string" || !f)) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' ${listName} must be an array of non-empty field names`,
    );
  }
  const schemaKeys = new Set(
    Object.keys(
      descriptor.schema && typeof descriptor.schema === "object" ? descriptor.schema : {},
    ),
  );
  for (const field of fields) {
    if (!schemaKeys.has(field)) {
      throw new PolicyError(
        `registerTool: tool '${descriptor.name}' ${listName}[*]='${field}' is not a key of descriptor.schema`,
      );
    }
  }
}

function _validateUntrustedInputs(descriptor) {
  _assertFieldsInSchema(descriptor, "untrusted_inputs");
}

function _validateSensitiveArgs(descriptor) {
  _assertFieldsInSchema(descriptor, "sensitive_args");
}

function _enforceUntrustedInputGate(args, descriptor) {
  const fields = descriptor.untrusted_inputs;
  if (!fields || fields.length === 0) return;
  if (args?.acknowledge_untrusted_input === true) return;
  for (const field of fields) {
    const value = args?.[field];
    if (typeof value === "string" && UNTRUSTED_FENCE_OPENER_RE.test(value)) {
      throw new PolicyError(
        `${descriptor.name}: arg '${field}' contains an untrusted-input fence; set acknowledge_untrusted_input: true to consume it`,
      );
    }
  }
}

// Substring an attacker-controlled producer output cannot be allowed
// to embed verbatim — a literal `[UNTRUSTED:logs:END]` inside a log
// line would visually terminate the fence and let the LLM treat the
// trailing bytes as trusted. Neutralize every `[UNTRUSTED:` in the
// body by replacing the leading bracket-keyword pair with a sentinel
// that preserves the text visually but does not lex as a fence
// boundary. Codex review #1201 cycle 1 finding 7 (security/class).
const UNTRUSTED_BODY_LITERAL = "[UNTRUSTED:";
const UNTRUSTED_BODY_ESCAPE = "[UNTRUSTED-ESC:";

function _escapeUntrustedBody(text) {
  return text.replaceAll(UNTRUSTED_BODY_LITERAL, UNTRUSTED_BODY_ESCAPE);
}

function _wrapUntrustedSource(result, descriptor) {
  const label = descriptor.untrusted_source;
  if (!label) return result;
  if (!result || !Array.isArray(result.content) || result.content.length === 0) {
    return result;
  }
  // Codex review #1201 cycle 2 finding: a multi-item text response
  // would previously leave items beyond content[0] outside the
  // trust-boundary fence even though the whole producer output is
  // by definition untrusted. Wrap every text item individually so
  // the contract — "all text content from this producer is fenced"
  // — holds regardless of how many content items the handler
  // emitted. Non-text items pass through unchanged.
  return {
    ...result,
    content: result.content.map((item) => {
      if (item?.type !== "text" || typeof item?.text !== "string") return item;
      const safeBody = _escapeUntrustedBody(item.text);
      return {
        ...item,
        text: `[UNTRUSTED:${label}:BEGIN]\n${safeBody}\n[UNTRUSTED:${label}:END]`,
      };
    }),
  };
}

export {
  _validateUntrustedSource,
  _validateUntrustedInputs,
  _validateSensitiveArgs,
  _enforceUntrustedInputGate,
  _wrapUntrustedSource,
};

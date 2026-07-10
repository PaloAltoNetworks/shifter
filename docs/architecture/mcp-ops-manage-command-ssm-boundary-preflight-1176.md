# MCP Ops Manage Command SSM Boundary Preflight

Issue: GitHub #1176, "`run_manage_command` allowlist accepts shell
metacharacters before SSM execution"

This is a requirement-free security preflight. The GitHub issue is the
shipping contract.

## Architecture Decision

`run_manage_command` is not protected by the ADR-010 local argv-array
boundary once its payload reaches `AWS-RunShellScript`. The local AWS CLI
argv helper prevents local shell evaluation; it does not make a remote shell
payload safe.

The fix must create a separate named boundary for the remote SSM command body:
management commands are parsed into a structured argv-like representation,
validated there, and only then rendered into the fixed remote invocation. The
allowlist remains command-level, but it is no longer sufficient to allowlist
only the first whitespace-delimited token.

## Canonical Incumbents

- `mcp/ops/index.js`: keep `run_manage_command` registered through
  `registerTool` with class `ssm_named`, `EnvSchema`, `Ec2Id`, and the
  existing `err()`/`ok()` envelope.
- `mcp/ops/policy.js`, `.shifter.yaml`, and `mcp/ops/audit.js`: keep session
  profile gating, prod confirmation, untrusted-input acknowledgement, and
  sanitized audit as the policy surface. Do not add a command-specific policy
  engine.
- `mcp/ops/lib.js`: keep the management-command validation and SSM argv builder
  as pure helpers so tests can assert the SSM `--parameters` JSON without
  spawning AWS.
- `mcp/shared/aws-helpers.js`: keep AWS CLI execution argv-array based. Do not
  introduce `exec`, `execSync`, `{shell: true}`, or a second AWS command helper.
- `mcp/ops/lib.test.js`, `mcp/ops/spawn-roundtrip.test.js`, and
  `mcp/ops/tool-surface.test.js`: add focused regression coverage at the helper
  boundary and preserve the live MCP surface expectations.
- `mcp/ops/SECURITY.md`, ADR-010, and ADR-014: keep the distinction between
  local process execution, operator-agent policy gates, and remote SSM shell
  payloads explicit.

## Required Cross-Cutting Layers

- MCP auth/policy surface: `run_manage_command` stays `ssm_named`, available
  only in profiles that include that class. `env=prod` must still pass the
  policy layer's explicit confirmation; command validation must not bypass or
  duplicate profile/env gates.
- Tool schema surface: keep the existing tool shape unless the implementation
  intentionally introduces an additive structured field. Any shape change must
  remain Zod-validated in `index.js`; deeper command semantics belong in
  `lib.js`.
- Untrusted-input surface: the `command` argument remains an
  `untrusted_inputs` field. Rejecting shell syntax must happen before SSM
  argument construction, and acknowledgements must not downgrade command
  validation.
- AWS CLI process surface: `buildSsmSendCommandArgs` must still pass
  `--parameters` as a single JSON argv element through the shared AWS helpers.
  This protects only the local host process boundary.
- Remote SSM shell surface: the rendered command sent to `AWS-RunShellScript`
  must contain a fixed wrapper plus validated argv elements only. Separators,
  command substitutions, redirects, pipes, backgrounding, quoting breakouts, and
  embedded newlines from user input must not be interpreted as remote shell
  syntax.
- OS/process exposure: do not put raw secrets into the command body, process
  argv, SSM command history, audit records, or error text. Management arguments
  should remain non-secret operational selectors.
- Error envelope and observability: errors should identify the invalid class of
  input without echoing attacker-controlled payloads. Audit continues to record
  sanitized arguments and result class through `mcp/ops/audit.js`.
- ADR/static guardrails: changes under `mcp/ops` must continue to satisfy
  `mcp-no-shell-exec` and the broader ADR guard suite.

## Extensibility Seam

The seam belongs in the management-command helper: a single parser/validator
that returns an argv-like structure and a single renderer for the remote
`docker exec portal python manage.py ...` invocation. Future changes such as
per-command option allowlists, additional read-only management commands, or a
non-portal container name should extend that helper or pass explicit parameters
into it; they should not scatter command string concatenation across handlers.

If command arguments need to grow beyond simple values, prefer a per-command
argument schema in `lib.js` over a generic shell-like grammar. The supported
language is "Django management command argv," not "remote shell."

## Gotchas And Anti-Patterns

- Do not treat shell escaping as the fix. Escaping is brittle here because the
  payload is intentionally interpreted by a remote shell after SSM receives it.
- Do not only check for semicolons. Cover command substitution, backticks,
  redirects, pipes, ampersands, control operators, quote breakouts, comments,
  carriage returns, and newlines.
- Do not parse with `trim().split(/\s+/)` and assume the first token carries the
  invariant. That is the bug class.
- Do not weaken `ssm_named` into `ssm_arbitrary` to get dry-run/two-phase
  behavior. This issue is about preserving a narrow named SSM command surface.
- Do not duplicate `.shifter.yaml` policy classes, Zod schemas, audit redaction,
  or AWS argv helpers in a local command-specific layer.
- Do not log the full rejected payload in thrown errors, MCP responses, test
  diagnostics, or audit-only helper output.

## Non-Goals

- No redesign of the `mcp/ops` policy engine or session profiles.
- No migration from AWS CLI helpers to an AWS SDK.
- No general-purpose shell parser or command runner.
- No expansion of allowed Django management commands unless required by the
  issue acceptance criteria.
- No behavioral change to free-form `ssm_send_command`; that remains the
  `ssm_arbitrary` class and is gated separately.
- No requirement or Ground Control traceability work for this issue.

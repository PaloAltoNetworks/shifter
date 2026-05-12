# MCP Ops Privileged Surface Preflight (revised)

Issue: GitHub #777, "`mcp/ops` grants any connected MCP client unrestricted
prod secrets, SQL, and remote-command access".

This note records the architecture boundary for hardening the
`shifter-ops` MCP server. **It is not an implementation plan.**

> ### Revision note
>
> An earlier draft of this preflight (and the first draft of ADR-014)
> scoped the issue as **strip privileged tools** — remove secret
> retrieval, arbitrary SQL, arbitrary SSM exec, infra mutation, and
> the `/dev-login/` tunnel from the general MCP surface. That scope
> assumed `mcp/ops` was a general-purpose MCP server whose connecting
> client might be untrusted.
>
> That assumption is wrong for this codebase. `mcp/ops` is the
> operator's own agent's working-day tool surface. Agents are
> *intended* to perform writes, mutations, SSM execution, and secret
> retrieval as routine range-operations work; stripping those tools
> would gut the product. The `/dev-login/` tunnel is intentional in
> dev because agents cannot complete MFA.
>
> The corrected scope (and ADR-014 as accepted) treats `mcp/ops` as an
> **operator agent surface**: privileged capability is retained, but
> gated through a structured per-tool policy layer. The real threat
> surface is **prompt injection** of the agent and **agent error**, not
> adversarial MCP clients. Defenses bound blast radius, not
> capability.

## Implementation status

This note describes the *full* policy-layer design. The work is split
across multiple PRs (this issue and its sub-issues) because the full
layer is too large to land at once. **The forward-looking sections
below describe behavior the layer enforces only after every phase
ships.** Today's status:

- **Phase 0 (this PR / #777) — DONE.** Architecture reframe: ADR-014
  reframed (R1 narrowed, R5 + R6 added), this preflight note
  rewritten, `mcp/ops/SECURITY.md` rewritten.
- **Phase 1 (this PR / #777) — DONE.** Policy seam: `.shifter.yaml`
  at repo root (`mcp_ops:` namespace), `mcp/ops/policy.js`
  (`parsePolicy`, `loadPolicy`, `profileFromEnv`, `Policy`,
  `registerTool`). `registerTool` enforces *class declaration and
  session-profile gating only* — it forwards descriptors to
  `server.tool` without wrapping the handler with the rest of the
  gates. Tools registered with a class disabled by the active profile
  are not registered at all; tools with no class or an undeclared
  class fail closed at registration.
- **Phase 2 — sub-issue #1198.** Composes env policy
  (`confirm_env="prod"`), dry-run defaults, description redaction,
  idempotency, audit log, and secret-handle return mode onto the
  wrapper.
- **Phase 3 — sub-issue #1199.** Adds two-phase `plan_*` →
  `execute_*`, session profile selection from
  `SHIFTER_OPS_PROFILE` (today the profile is read by an explicit
  caller, not yet by the server entrypoint), and rate caps.
- **Phase 4 — sub-issue #1200.** Adds untrusted-input fencing and
  apex out-of-band operator approval.
- **Phase 5 — sub-issue #1201.** Converts each of the 45
  `server.tool(...)` call sites in `mcp/ops/index.js` to
  `registerTool(...)` descriptors with capability-class tags. **Until
  Phase 5 lands, every tool in `mcp/ops/index.js` is still a direct
  `server.tool(...)` registration, and `.shifter.yaml` /
  `SHIFTER_OPS_PROFILE` have no runtime effect on the live server.**
- **Phase 6 — sub-issue #1202.** Adds `mcp/ops/tool-surface.test.js`
  asserting the policy-layer invariants on the live registered
  surface.

The rest of this note describes the design — capability classes,
gates, cross-cutting layers, gotchas — as it stands once all six
phases ship.

## Decision Boundary (corrected)

`mcp/ops` is an operator agent MCP surface in the sense of
ADR-014-R5. Its tools may expose privileged capability — secret
retrieval, named and arbitrary SQL, named and arbitrary SSM execution,
infrastructure mutation, and a dev-only auth-bypass tunnel for agent
sessions that cannot complete MFA — but every tool MUST be governed by
a structured per-tool policy layer.

The policy layer declares each tool's capability class
(`observability | named_db_read | named_db_write | secret_handle |
ssm_named | ssm_arbitrary | db_arbitrary | infra_mutation |
dev_bypass_tunnel`) and enforces, at minimum:

- Explicit environment selection. `prod` is never the default; tools
  that touch prod require an explicit `confirm_env="prod"` argument.
- Dry-run defaults for `infra_mutation`, `ssm_arbitrary`, and
  `db_arbitrary` classes. Real execution requires `execute=true`, and
  for the strongest cases a two-phase `plan_<name>` →
  `execute_<name>` exchange with a single-use, short-TTL plan id.
- Secret references, not values. `secret_handle` tools return an
  opaque handle resolvable only inside the server process; raw secret
  bytes never reach MCP responses or LLM context.
- Structured per-call audit. Every invocation appends a JSONL record
  with sanitized arguments and outcome.
- Session profile gating. `SHIFTER_OPS_PROFILE=read_only | standard |
  destructive` selects which capability classes are even registered as
  tools at server startup. `standard` is the default and excludes the
  most dangerous classes.
- Out-of-band operator confirmation for apex operations
  (production termination, drop-table-equivalent writes, secret
  rotation): the server prompts the operator's terminal directly and
  fails closed on timeout.

Tool descriptions reachable via `list_tools` MUST NOT contain
auth-bypass procedures. The dev-login tunnel is retained as a tool,
but its description is redacted (no `/dev-login/` URL text, no
step-by-step bypass language) — the capability stays; the procedural
text does not.

## Threat model

The agent is the operator. The trust boundary is **not** MCP client
vs server (the agent loop is trusted); it is **agent intent** vs
**everything that can manipulate the agent's prompt**.

1. **Prompt injection.** Adversarial text reaches the LLM through any
   channel it reads as tool result content: `get_log_events`,
   `filter_log_events`, `tail_logs`, `get_s3_object`,
   `ssm_get_command_output`, range guest stdout returned via SSM,
   external web fetches, the body of an issue the agent is told to
   work on, comments on a PR. The injected text instructs the agent
   to perform a destructive action it would not otherwise have chosen.
2. **Agent error.** Hallucination, wrong instance id, dev/prod
   confusion, missing WHERE clause, double execution on retry. Not
   malicious — just wrong.

Defenses target both: the policy layer bounds blast radius regardless
of why the agent invoked a destructive tool.

## Canonical Incumbents

- `mcp/shared/aws-helpers.js`, `mcp/ops/lib.js`, `mcp/ops/lib.test.js`,
  and `mcp/ops/spawn-roundtrip.test.js`: canonical AWS CLI
  argv-array boundary. The policy layer wraps these, not replaces them.
- `mcp/ops/index.js`: existing MCP registration point and Zod input
  shape layer. Phase 5 (sub-issue #1201) converts each
  `server.tool(...)` call site to a
  `registerTool({server, policy, audit, planStore}, descriptor)` call
  that tags the tool with a capability class and lets the policy
  layer compose the gates. Until Phase 5 lands, the live registration
  point still calls `server.tool` directly and `.shifter.yaml` does
  not gate it.
- `mcp/ngfw/SECURITY.md` and `mcp/ngfw/tool-surface.test.js`: closest
  surface-test precedent. `mcp/ops/tool-surface.test.js` follows the
  same shape — assertions about which tools are present under which
  profile, and which behaviors the gates enforce.
- `mcp/ops/SECURITY.md`: package-local security rules. Rewritten in
  this PR to describe the policy layer and operator-agent threat
  model.
- `.shifter.yaml` (new): repo-root runtime config. `mcp_ops:`
  namespace holds the per-tool policy. Follow-up #1197 will evolve the
  file into the unified runtime config.
- `shifter/installation/schema.py`, `shifter/installation/contract.py`,
  and `shifter/installation/errors.py`: repository precedent for
  treating secret values as sensitive (references, not raw values) and
  sanitizing error envelopes. The `secret_handle` class mirrors this
  in the MCP layer.
- `shifter/shifter_platform/config/dev_auth.py` and
  `config/settings.py`: canonical dev-login boundary. The dev-bypass
  tunnel remains the agent's path through that boundary; the policy
  layer guards the tunnel's MCP surface (allowed_envs=[dev],
  description_redaction) without re-implementing the
  authentication-policy logic.

## Cross-Cutting Layers

- MCP tool surface: every registered tool carries a capability class
  tag. Class membership drives every policy gate (env, dry-run,
  audit, profile, rate cap, idempotency, two-phase, secret return
  mode).
- Environment binding: `EnvSchema`, `PROFILES`, and
  `PANW_SHIFTER_*_PROFILE` select credentials. The policy layer adds
  the *authorization* the env arg doesn't supply: no default-to-prod
  for prod-touching classes, explicit `confirm_env="prod"` required.
- Tool input validation: existing Zod schemas and `lib.js` helpers stay
  as syntax/shape validation. The policy layer composes additional
  schema fields (`confirm_env`, `execute`, `idempotency_key`,
  `acknowledge_untrusted_input`) automatically per class.
- AWS process boundary: unchanged. All AWS calls continue through
  `mcp/shared/aws-helpers.js` and argv arrays. The policy layer never
  reaches the shell.
- Secret handling: `secret_handle` class returns references, not
  values. Internal callers (`fetchCredentials` for the DB pool open)
  resolve handles inside the server process. No raw bytes ever enter
  MCP responses.
- Database boundary: `query`, `execute`, `list_tables`, and
  `describe_table` remain registered for sessions that opt into the
  `destructive` profile. They are gated by dry-run defaults and
  two-phase plan→execute, audited per call, and rate-capped. Named
  read/write diagnostics (`list_risks`, `get_risk`, the rest of the
  risk_register surface, `list_ranges`, `get_range`, etc.) are
  registered under `named_db_read` / `named_db_write` and remain
  available under the `standard` profile.
- Remote execution boundary: `ssm_send_command`,
  `ssm_get_command_output`, and `run_manage_command` are retained.
  `ssm_arbitrary` is dry-run-by-default and two-phase. `ssm_named`
  (the allowlisted manage.py path) is direct-execute.
- OS/runtime exposure: `start_portal_test_tunnel` and
  `stop_portal_test_tunnel` are retained under the `dev_bypass_tunnel`
  class. Allowed only when `env=dev`. Tool description is redacted —
  the capability is there for agents that need to authenticate without
  MFA, but the registry text does not document the bypass procedure.
- Error envelopes: `err()` is updated to refuse echoing secret values,
  raw SQL, and raw shell command bodies into the error message; the
  policy wrapper sanitizes errors with the same redact list as audit.
- Logging and audit: a stdio MCP call still has no platform actor
  identity. The audit log records what the agent did, in what env,
  with what arguments (sanitized), and what the result class was, so
  the operator has a forensic record even though there is no
  multi-actor RBAC.

## Extensibility Seam

The seam is the central per-tool capability policy in `.shifter.yaml`.
The policy declares classes, class defaults (execute_default,
two_phase, rate_cap, return_mode, allowed_envs,
description_redaction, idempotency_key), session profiles, and
per-tool overrides. Adding a new tool is one descriptor entry; adding
a new class is one entry in the `classes:` list plus one
`class_defaults:` block.

Follow-up #1197 evolves `.shifter.yaml` from the `mcp_ops:` namespace
into a unified repo-root runtime configuration without renaming the
file or breaking the policy schema.

## Gotchas

- A capability class tag is required for every registered tool. The
  policy wrapper fails closed if a tool is registered without one.
- The session profile is read at startup; it gates whether a class is
  ever registered. Changing profile requires a server restart. This
  is intentional — runtime profile flips would be a confused-deputy
  surface.
- Plan ids are single-use and short-TTL (60s). Long agent
  conversations cannot pre-plan-and-batch destructive ops.
- The `[UNTRUSTED:<source>]` fence on returned text is a *cooperative*
  signal to the LLM. The actual gate is the
  `acknowledge_untrusted_input` flag on tools that consume free-form
  text from untrusted sources; without it, the call is refused.
- Apex operator confirmation reads from the operator's terminal. In
  CI / headless runs the apex tool fails closed, which is correct.
- Description redaction strips procedural bypass text, but a tool's
  *name* still appears in `list_tools`. Operators who don't want even
  the name visible should switch session profile to `standard` (which
  excludes `dev_bypass_tunnel`).
- The DB tunnel + pool + `fetchCredentials` machinery is retained.
  Its credentials never leave the server process; the audit log
  records that the agent opened a tunnel but not the credential
  bytes.

## Non-Goals

- Replacing AWS-CLI helpers with an SDK migration (ADR-010 owns the
  command-execution boundary; this PR does not touch that).
- Adding multi-actor RBAC, OAuth, or any external identity system to
  the MCP server. The operator agent loop is the trusted actor; the
  policy layer protects the agent from itself and from prompt
  injection, not from other actors.
- Removing useful capability solely because it is privileged. The
  capability is the product; the policy layer is the safety belt.
- Building the unified runtime config surface. That is #1197; this PR
  introduces `.shifter.yaml` scoped to `mcp_ops:` and leaves the
  consolidation to the follow-up.

## Validation For The Implementation

Run the repo architecture gate for changes to `mcp/ops`, ADRs, or
guardrails:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

For `mcp/ops` code changes, also run:

```bash
cd mcp/ops && npm test
cd mcp/ops && npm run lint
```

The surface tests at `mcp/ops/tool-surface.test.js` are the
load-bearing invariant for ADR-014-R3 on this surface: they assert
that every capability class behaves as the policy declares (dry-run
gating, secret reference returns, prod confirmation refusal, profile
gating, redacted descriptions). Changes to `mcp/ops/index.js` or
`.shifter.yaml` that break a surface test break the ADR-014-R5
guarantee.

# shifter-ops MCP security guardrails

The ops MCP server runs with the local operator's AWS credentials and
can reach production-facing AWS APIs, the production database, and the
operator's own range infrastructure. **`shifter-ops` is an *operator
agent surface*** in the sense of ADR-014-R5 — the intended client is
the operator's own trusted agent loop, and agents are *meant* to
perform writes, mutations, SSM execution, and secret retrieval as
routine range-operations work.

The threat surface is therefore **not** "untrusted MCP client connects
to the server." It is:

1. **Prompt injection** of the agent through any text it reads
   (`get_log_events`, `filter_log_events`, `tail_logs`,
   `get_s3_object`, `ssm_get_command_output`, range guest stdout, web
   fetches, issue/PR bodies, teammate comments).
2. **Agent error** — hallucination, wrong instance id, dev/prod
   confusion, missing `WHERE` clause, retry storms.

Defenses bound the blast radius of any single call, not the
capabilities of the agent.

## Implementation status

This document describes the **target policy layer**, which is being
landed in phases (issue #777 + sub-issues #1198–#1202). Today's
runtime status:

- `.shifter.yaml` exists at the repo root and `mcp/ops/policy.js`
  provides `parsePolicy`, `loadPolicy`, the `Policy` class, the
  `registerTool` wrapper, and (after Phase 2 / #1198) the
  composed-gate wrap. Phase 1 enforcement (class declaration and
  session-profile gating) is unchanged. Phase 2 (#1198) added five
  cheap-defense gates at the seam: env confirmation, dry-run
  defaults, description redaction, idempotency keys, secret-handle
  return-mode, and a per-call JSONL audit append via
  `mcp/ops/audit.js`. The gates compose around every handler
  registered through `registerTool`.
- Higher-cost gates (two-phase plan/execute, rate caps,
  untrusted-input fencing, apex out-of-band approval) **are not yet
  wrapped around handlers.** They land in #1199 (Phase 3) and
  #1200 (Phase 4).
- The 45 tools in `mcp/ops/index.js` **are not yet registered through
  `registerTool`** — that is Phase 5 (#1201). Until then,
  `.shifter.yaml` and `SHIFTER_OPS_PROFILE` have **no runtime effect
  on the live server**; the Phase 2 gate code exists at the seam but
  the live registration path is unchanged.
- `mcp/ops/tool-surface.test.js` (the load-bearing
  ADR-014-R3 / R5 invariant suite referenced below) is Phase 6
  (#1202) and **does not yet exist**.

The rest of this document describes the policy layer as it stands
once every phase ships.

## Policy layer — target design (phased rollout)

The sections below describe the **target** policy layer once every
phase ships. The Implementation Status section above is authoritative
for what is live in the current tree; everything here is design /
specification for the in-flight rollout (issue #777 + sub-issues
#1198–#1202).

Every tool registered on this server is governed by a structured
per-tool policy declared in `.shifter.yaml` (`mcp_ops:` namespace at
the repo root). The policy assigns each tool exactly one **capability
class**:

| Class | What it covers |
|-------|----------------|
| `observability` | CloudWatch logs, `describe-*`, `list-*` — no writes, no secrets |
| `named_db_read` | Named, parameterized read-only DB diagnostics (`list_risks`, `get_risk`, ranges, etc.) |
| `named_db_write` | Named, parameterized DB mutations (`create_risk`, `update_risk`, etc.) |
| `secret_handle` | `get_secret`, `list_secrets` — returns references, not raw values |
| `ssm_named` | Allowlisted Django manage.py commands via SSM |
| `ssm_arbitrary` | Free-form SSM `send-command` / `get-command-invocation` |
| `db_arbitrary` | `query`, `execute`, `list_tables`, `describe_table` |
| `infra_mutation` | `start_ec2_instance`, `stop_ec2_instance`, `terminate_ec2_instance`, `restart_ecs_service`, `reconcile_ranges` |
| `dev_bypass_tunnel` | `start_portal_test_tunnel`, `stop_portal_test_tunnel` (agent auth without MFA in dev) |

Class membership drives the gates the policy wrapper composes around
each handler:

- **Session profile.** `SHIFTER_OPS_PROFILE=read_only | standard |
  destructive` selects which classes are registered as tools at server
  startup. Default `standard` excludes `ssm_arbitrary`, `db_arbitrary`,
  `infra_mutation`, and `dev_bypass_tunnel`. Operators opt into the
  `destructive` profile per session when they need those capabilities.
- **Environment policy.** No default to `prod`. Tools that touch prod
  require an explicit `confirm_env="prod"` argument; otherwise the
  call is refused before the handler runs.
- **Dry-run defaults.** `infra_mutation`, `ssm_arbitrary`, and
  `db_arbitrary` classes default to dry-run. The handler returns a
  preview of what *would* happen; real execution requires
  `execute=true`. For the highest-impact subset (apex ops), a
  two-phase `plan_<name>` / `execute_<name>` exchange is used with a
  single-use, short-TTL plan id.
- **Secret handles.** `secret_handle` tools return an opaque handle
  (`shf-secret:<uuid>`) resolvable only inside the server process.
  Raw secret bytes never enter MCP responses or LLM context. Internal
  helpers (`fetchCredentials` for the DB pool open) accept the
  handle and resolve it server-side.
- **Idempotency keys.** `named_db_write` mutations require an
  `idempotency_key` argument. Same key on retry returns the cached
  result, so an agent retry storm cannot compound.
- **Rate caps.** `infra_mutation` defaults to `{count: 3, window: 60s}`
  — after three mutations in a minute, further calls are refused
  until the window resets.
- **Audit.** Every invocation appends a JSONL record to
  `~/.shifter-ops-audit.jsonl` (configurable): timestamp, tool,
  class, env, profile, sanitized arguments, result class, duration,
  plan id if any, idempotency key if any, error class if any.
- **Description redaction.** `dev_bypass_tunnel` tool descriptions
  are stripped of bypass procedures and URLs (per ADR-014-R6) before
  they reach `list_tools`. The capability is retained; the
  procedural text is not.
- **Untrusted-input fencing.** Tools that return text from untrusted
  sources (logs, S3 objects, SSM stdout, web fetches) wrap their
  output in `[UNTRUSTED:<source>:BEGIN] ... [UNTRUSTED:<source>:END]`
  fences. Tools that consume free-form text (`query`, `execute`,
  `ssm_send_command`, `run_manage_command`) refuse calls whose text
  arg contains those fences unless `acknowledge_untrusted_input: true`
  is also set, forcing the agent to acknowledge it is intentionally
  acting on text from an untrusted source.
- **Apex out-of-band confirmation.** A small set of apex operations
  (`terminate_ec2_instance` against prod, `execute_plan` for
  `db_arbitrary` writes against prod, `restart_ecs_service` against
  prod) require operator-terminal confirmation before executing: the
  server prints a token to stderr and pauses up to 60s waiting for
  the operator to type it back via a dedicated `approve` tool. Fails
  closed on timeout.

The `.shifter.yaml` policy is the source of truth. The policy wrapper
fails closed if a tool is registered without a class, or if
`.shifter.yaml` is missing or malformed at startup.

## Database TLS

`mcp/ops` connects to the per-environment RDS Postgres database
through an SSM port forward (`localhost:<local_port>` → RDS endpoint
`:5432`). The pool is constructed by
`mcp/ops/lib.js::buildPoolConfig`, which is the single source of
truth for the TLS configuration.

**Trust model.**

- TLS verification stays on (`rejectUnauthorized: true`). Disabling
  verification — even as a documented exception — is rejected by
  ADR-014-R7 and by the `mcp-ops-tls-strict` adr_guard check.
- The tunnel terminates at `localhost`, but the RDS-issued cert
  carries the RDS endpoint in its CN/SAN. `buildPoolConfig` sets
  `ssl.servername` to the RDS endpoint discovered when the SSM
  tunnel was started (`tunnels[env].rdsHost`). Node's `tls.connect`
  uses `servername` for both SNI and the default
  `checkServerIdentity` hostname check, so verification fires
  against the real RDS endpoint rather than the localhost target of
  the port forward.
- The cert chain is rooted at Amazon Root CA 1, which is present in
  every mainstream OS root store, so the default Node trust store
  verifies the chain. No bundled CA is shipped in this repo at
  present.

**Switching to a pinned CA bundle.** If the OS trust store ever
proves insufficient (e.g., for an air-gapped host whose root bundle
is curated separately), download AWS's published global RDS bundle
from `https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem`,
commit it under `mcp/ops/certs/rds-global-bundle.pem`, document the
sha256 + refresh procedure in this file, and pass
`ca: readFileSync(<path>)` alongside the existing `servername` in
the `ssl` block. The check sites stay the same; only the trust
input changes.

**Regression coverage.** `mcp/ops/lib.test.js`'s `buildPoolConfig`
describe block asserts the SSL invariants (verification on,
servername set, fail-closed when `rdsHost` is empty / missing /
non-string). The `mcp-ops-tls-strict` adr_guard check is a
defense-in-depth backstop that flags any other JS file under
`mcp/ops/` that re-introduces `rejectUnauthorized: false`.

## AWS CLI execution (unchanged)

The argv-array boundary from ADR-010 is unchanged by this policy
layer:

- AWS CLI helpers must execute `aws` with an argument array via
  `spawn`/`spawnSync`/`execFile`, never by interpolating a shell
  command string.
- Shared AWS helpers accept structured argv segments, not a pre-joined
  command string. Call sites pass JSON values as a single argv element
  after `JSON.stringify`.
- Shell escaping is not a remediation strategy. If a value must be
  interpreted by a remote shell through SSM, that interpretation is
  isolated to the remote command payload and never routed through
  the local MCP host shell.
- Do not add a second AWS command builder. Extend the shared helpers
  in `mcp/shared/aws-helpers.js`.
- `execSync` import remains forbidden in this package per ADR-010-R1
  and the `mcp-no-shell-exec` static check.

## Validation and boundaries (target — phased rollout)

These describe the target policy layer; today only the seam exists
(see Implementation Status above).

- Reuse the existing Zod schemas in `index.js` for tool input shape
  and the shared helpers in `lib.js` for domain constraints
  (`resolveLogGroup`, `buildInstanceFilters`, `getSsmDocument`,
  `validateManageCommand`, `MAX_S3_READ_SIZE`, `isBinaryContentType`).
  The policy wrapper composes additional schema fields automatically
  per class (`confirm_env`, `execute`, `idempotency_key`,
  `acknowledge_untrusted_input`) once Phases 2–4 ship.
- Zod validation is defense in depth, not the authorization boundary.
  The policy layer (once fully rolled out) is the authorization
  boundary on this surface.
- Keep capability policy separate from syntax validation. Read-only
  SQL, Secrets Manager names, EC2 IDs, and SSM command IDs can be
  syntactically valid and still need to be gated by class policy.

## Output, errors, and audit (target — phased rollout)

These describe the target policy layer; today only the seam exists.

- MCP responses must not include raw secret values, private keys, DB
  passwords, OIDC client secrets, full secret-bearing URLs, raw SQL
  text, or shell command bodies. The `secret_handle` class enforces
  this by construction once #1198 lands.
- Error envelopes identify the failed operation with sanitized
  identifiers. The policy wrapper sanitizes errors using the same
  `audit.redact` list as the audit log; raw AWS stderr, raw DB
  errors, and multiline user input never reach error text.
- The audit log carries actor context (process pid, profile in use,
  env), operation name, sanitized target identifiers, result class,
  and request/correlation id when one is present. There is no
  external identity system; the operator owns the audit file.

## Regression coverage

Current (this PR, #777):

- `mcp/ops/spawn-roundtrip.test.js` proves that Node's `spawnSync`
  forwards argv elements byte-for-byte across the boundary. (Shared
  across MCP servers via `mcp/shared/aws-helpers.js`.) Unchanged.
- `mcp/ops/lib.test.js` covers AWS argv builders for individual call
  sites — CloudWatch filters, SSM command parameters,
  management-command SSM payloads, S3 bucket/key inputs. Unchanged.
- `mcp/ops/policy.test.js` covers the **current** scope of the policy
  wrapper: `parsePolicy` shape validation (top-level keys,
  class-defaults coverage per declared class, profile membership,
  version, env block), `loadPolicy` parsing the real `.shifter.yaml`,
  the `Policy` class lookups (`classDeclared`, `classEnabled`,
  `classDefaults`, `envDefault`, `envProdRequiresConfirm`), and
  `registerTool`'s class-tag + profile gating (class-disabled tools
  are not registered; missing / undeclared classes fail closed).

Target (added by sub-issues):

- `mcp/ops/policy.test.js` extended in #1198–#1200 to cover env
  policy, dry-run gating, idempotency, rate caps, audit append,
  secret-handle return mode, two-phase plan→execute, untrusted-input
  fencing, description redaction. Those gates do not yet exist in
  this PR.
- `mcp/ops/tool-surface.test.js` (added by #1202) is the
  load-bearing surface invariant for ADR-014-R3 / R5 on this server:
  every capability class behaves as policy declares; profile gating
  actually removes tools from the registry; `dev_bypass_tunnel`
  descriptions do not contain bypass procedures. The file does not
  yet exist in this PR.

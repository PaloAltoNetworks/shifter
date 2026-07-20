# MCP Ops Modularization Preflight

Issue: GitHub #690, "Refactor MCP ops server monolith"

This is a requirement-free maintenance preflight. The GitHub issue is the
shipping contract. The refactor must preserve the effective MCP surface that
exists after `.shifter.yaml` policy composition, not merely the base tool names
written in source.

## Architecture Decision

`mcp/ops/index.js` is the executable composition root. It should own only live
process wiring: create the MCP server, install the shared schema-dialect
normalizer, load the policy and startup profile, assemble the tool registrars,
connect stdio, and install/clean up process-scoped resources. Importing the
entrypoint or any tool module must remain side-effect free.

Bounded operation modules should own cohesive descriptor groups (logs, compute,
database diagnostics, risk register, S3/state, costs, image workflows, and SSM
operations). A descriptor is one atomic contract: base tool name, description,
Zod input shape, capability class, trust/redaction metadata, write marker, and
handler. Do not split those facts across parallel registries.

One explicit `registerAllOpsTools(ctx)` aggregation seam must invoke every
bounded registrar through `mcp/ops/policy.js::registerTool` and run
`validateApexCoverage` once after the complete descriptor set is seen. Domain
registrars must never call `server.tool` directly. This preserves profile
suppression, `plan_`/`execute_` expansion, policy schema augmentation, audit,
secret handles, untrusted-input fencing, rate caps, idempotency, and apex
approval as one cross-cutting pipeline.

No new ADR is needed. ADR-010 governs command execution and ADR-014 governs the
operator-agent surface. Their evidence paths and the scoped live-identifier
exception in `docs/adr/exceptions.yaml` must be updated in the implementation if
code moves out of `index.js`.

## Existing Boundaries To Reuse

- `.shifter.yaml` plus `mcp/ops/policy.js` are the only capability-policy and
  policy-config validation layer. Capability classes, environment confirmation,
  policy-added fields, profiles, dry-run/two-phase behavior, idempotency, rate
  caps, secret handles, untrusted-input fencing, and apex approval stay there.
- `mcp/ops/audit.js` is the only audit/redaction writer. Preserve its recursive
  argument sanitizer, descriptor-specific field redaction from `policy.js`,
  JSONL shape, best-effort failure behavior, and owner-only file/directory modes.
- `mcp/shared/aws-helpers.js` is the canonical AWS CLI process boundary.
  `mcp/ops/lib.js` already re-exports it and contains focused argv, GitHub,
  SQL-update, S3, management-command, and TLS helpers. Move or narrow these only
  when ownership becomes clearer; do not create a second AWS executor or retain
  duplicate compatibility implementations.
- `mcp/shared/tool-schema-dialect.js` is the server-wide MCP schema compatibility
  shim and is installed once at bootstrap.
- Existing Zod objects are the MCP request-shape contract. Shared primitives
  such as `EnvSchema`, EC2/SSM identifiers, safe names/paths, ARNs, AMI/image
  types, and risk enums may move to one schema module. Operation-only schemas
  should remain beside their descriptor. Do not reproduce these shapes as DTOs,
  JSON Schema, hand validation, or policy config.
- Semantic validators remain distinct from transport shape validation:
  `resolveLogGroup`, `buildInstanceFilters`, `FORBIDDEN_PATTERN`,
  `validateManageCommand`, `MAX_S3_READ_SIZE`, `isBinaryContentType`, and
  `buildPoolConfig` are canonical incumbents. Zod acceptance does not replace
  these domain/security checks.
- Database access currently has one process-scoped tunnel/pool/credential owner
  and one `withClient` seam. Preserve one lifecycle owner, read-only session
  handling, parameterized SQL, bounded pools, verified TLS, and idempotent
  cleanup. Do not create a pool, tunnel, repository hierarchy, or transaction
  convention per handler.
- `ok`/`err` are the existing MCP response envelope. Extract them once if needed
  for modules; do not create per-domain envelopes or an exception hierarchy.
  Handler-thrown failures must still flow through the policy wrapper so refusal
  and failure audits are not bypassed.
- `mcp/ops/lib.js::DEFAULT_GITHUB_REPO`, `.ground-control.yaml`, and the repo
  rules all identify `Brad-Edwards/shifter` as canonical. Workflow dispatch must
  retain the existing fixed workflow names, `dev` promotion refs, structured
  `-f key=value` argv, and token environment binding. There is no Ground Control
  interaction in the current server; this refactor must not invent one.

## Cross-Cutting Layers The Design Must Pass

| Layer | Required invariant |
|---|---|
| MCP bootstrap | `McpServer`, the schema-dialect normalizer, policy load, full registration, stdio connect, and process handlers happen once in the composition root; imports do not connect, spawn, register signals, or write audit files. |
| MCP request shape | The same Zod schemas, defaults, optionality, descriptions, limits, and regexes reach `registerTool`; the policy wrapper remains the only layer that augments schemas with control fields. |
| Auth/capability policy | Every descriptor carries exactly one existing class and reaches `registerTool`; active profile selection is read once at startup through `profileFromEnv`, disabled classes remain absent from `list_tools`, and `validateApexCoverage` sees the complete descriptor set. |
| Environment/config | `.shifter.yaml` continues through `loadPolicy` and fails closed on malformed policy. `SHIFTER_OPS_PROFILE`, `PANW_SHIFTER_DEV_PROFILE`, and `PANW_SHIFTER_PROD_PROFILE` retain their current roles; `env` is selection, not authorization, and prod still requires policy confirmation. |
| Secret handling | Raw Secrets Manager values and DB credentials stay server-side in memory and pool configuration. Secret-bearing tools return policy-managed handles. `GH_TOKEN`/`GITHUB_TOKEN` are passed in the child environment, never argv or MCP output. Apex tokens remain stderr-only and excluded from audit. |
| Local OS/process | AWS, GitHub, and Git calls use fixed executables plus argv arrays; no `exec`, `execSync`, shell strings, or `{shell: true}`. Long-lived SSM port forwards retain one owner and cleanup path. AWS profile names in argv are selectors, never secret material. |
| Remote execution | Local argv safety does not sanitize an SSM remote shell body. `run_manage_command` must continue through `validateManageCommand` and `buildRunManageArgs`; arbitrary SSM remains separately classified and two-phase gated. |
| Database/TLS | `buildPoolConfig` remains the single TLS constructor with `rejectUnauthorized: true` and `ssl.servername` set to the discovered RDS endpoint across the localhost SSM tunnel. Read paths retain `withClient(..., {readOnly: true})`; writes remain parameterized and explicitly classified. |
| Persistence | Direct operator SQL remains behind `withClient`; no new application repository or platform-service abstraction is implied by this file split. Risk table names, enums, update-set construction, and legacy table classification retain one source of truth. |
| Output/error | Tool success/error shapes remain MCP-compatible and untrusted producers remain fenced. Never echo raw SQL, remote commands, secrets, multiline input, or newly broadened CLI/DB diagnostics into responses or logs. The current common `err(e)` exposes dependency error messages; changing that behavior requires an intentional, separately tested compatibility/security decision, not divergent per-module mappers. |
| Observability | Every live invocation still crosses `policy.js` and `audit.js`; plan/execute correlation, result/error class, profile/env, idempotency key, and descriptor-aware redaction remain intact. Tests must redirect audit output to a temporary path. |
| Static/repo policy | New modules remain covered by `mcp-no-shell-exec`, `mcp-ops-tls-strict`, `no-live-cloud-identifiers`, ESLint security rules, Sonar analysis, and the `mcp_ops` CI path filter. Moving exempt state-bucket identifiers requires moving the scoped ADR exception path, not copying the identifiers or broadening the exception. |

## Module And Test Guardrails

The extraction boundary is a cohesive descriptor group, not one tiny file per
tool and not one new universal controller/service/repository stack. A domain
registrar may accept a narrow set of explicit dependencies for focused tests
(for example an AWS runner or `withClient`); avoid a mutable global service
locator or a single giant dependency bag. Process-scoped state belongs to its
lifecycle module, while pure builders/validators stay stateless.

`mcp/ops/tool-surface.test.js` remains the authoritative whole-surface test. It
must call the new aggregation seam with the real policy parser and fake server,
not parse source text or duplicate policy composition. Preserve its hard-coded
profile sets and descriptor metadata checks. Handler tests should import the
bounded handler/registrar without booting stdio or touching real AWS, GitHub,
Postgres, operator audit files, home-directory state, or process signal
handlers. Split the large `lib.test.js` by behavior boundary only as production
helpers move; retain `policy.test.js`, `audit.test.js`, and
`spawn-roundtrip.test.js` as cross-cutting suites rather than cloning them per
domain.

The public compatibility baseline includes:

- base descriptor names and the profile-dependent effective names, including
  all generated `plan_<name>` / `execute_<name>` pairs;
- descriptions after policy redaction, request schema defaults/constraints plus
  policy-added fields, response content/isError shapes, and descriptor metadata;
- current AWS/GitHub argv, SQL parameterization, policy/audit events, and
  lifecycle cleanup behavior where observable.

## Extensibility Seam

The required seam is the explicit registrar aggregation plus narrow dependency
injection at a domain boundary. Adding the next tool in an existing domain
should change that domain registrar and its focused tests, the centralized
surface expectation, and—only when relevant—`.shifter.yaml` apex/untrusted
configuration and `SECURITY.md`. It should not require editing bootstrap,
policy composition, audit, or command executors.

A genuinely new capability class remains a deliberate cross-cutting change to
`.shifter.yaml`, policy validation/invariants, surface tests, security docs, and
ADR-014 evidence. A new tool must not smuggle a new class or gate into its domain
module.

## Gotchas And Anti-Patterns

- Do not call `server.tool` outside `policy.js`; that silently bypasses every
  ADR-014 gate.
- Do not separate tool names/classes/trust metadata from schemas and handlers
  into parallel maps that can drift, and do not dynamically discover registrars
  from the filesystem. The complete descriptor set must be explicit and
  deterministic for policy coverage and review.
- Do not confuse the base descriptor name with the effective MCP surface:
  two-phase classes expose generated pairs and disabled classes expose nothing.
- Do not read profiles or policy independently in each module. Multiple config
  snapshots create time-of-check/time-of-use and confused-deputy behavior.
- Do not duplicate Zod shape checks in handlers, encode semantic policy in Zod,
  or move capability policy into domain code.
- Do not turn `lib.js` into another monolith under a new name, but also do not
  replace it with dozens of one-function modules or copy helpers during a staged
  move. A temporary re-export facade is safer than two implementations.
- Do not add generic controllers, DTOs, repositories, event buses, or exception
  classes merely to mirror a web-service architecture. This is an in-process
  stdio MCP composition with policy-wrapped operation handlers.
- Do not make handler tests depend on `index.js`, live environment variables,
  home-directory audit files, open ports, signal registration, or subprocesses.
- Do not relax TLS, shell, SQL, S3-size/binary, prod-confirmation, or output
  redaction checks to make extraction easier.
- Do not silently alter error text or return serialization during moves. If a
  security hardening intentionally changes an externally visible error, isolate
  and document that migration with compatibility tests.

## Non-Goals

- No MCP tool addition/removal, capability reclassification, schema migration,
  response redesign, or behavioral cleanup beyond what is required to preserve
  behavior while extracting modules.
- No redesign of `.shifter.yaml`, `policy.js`, `audit.js`, profiles, or the
  plan/execute protocol.
- No AWS SDK migration, database ORM/repository layer, Ground Control client,
  provider-neutral cloud abstraction, or new persistence mechanism.
- No change to application-layer Risk Register services or their auth model;
  the existing operator-MCP direct SQL path is a separate bounded surface.
- No relocation of runtime configuration, live state-bucket identifiers, or
  audit persistence as part of the module split.
- No implementation work in this preflight.

## Repository-Wide Verification Surface

The implementation is expected to preserve the contracts enforced by:

- `mcp/ops/{SECURITY.md,policy.js,audit.js,lib.js,tool-surface.test.js}` and the
  newly focused handler/helper tests;
- `mcp/shared/{aws-helpers.js,tool-schema-dialect.js}`;
- `.shifter.yaml`, `.ground-control.yaml`, ADR-010, ADR-014, and any affected
  scoped entry in `docs/adr/exceptions.yaml`;
- `.github/quality-path-filters.yaml`, `.github/workflows/_quality.yml`,
  `.pre-commit-config.yaml`, `sonar-project.properties`, and
  `scripts/adr_guard/adr_guard.py`.

The normal validation is `npm run lint` and `npm test` from `mcp/ops`, followed
by `python3 scripts/adr_guard/adr_guard.py --all --level ci` for the architecture
and MCP security checks.

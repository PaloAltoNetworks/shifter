# NGFW MCP Security Documentation Preflight (#1191)

Status: pre-implementation guidance

Date: 2026-05-13

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1191>

## Scope Boundary

This workstream updates the threat model documentation for the current
`shifter-ngfw` MCP server. It is documentation and guardrail alignment, not a
feature change. The GitHub issue title, body, and acceptance criteria are the
shipping contract.

Do not reintroduce removed NGFW administration capabilities to make old security
text true. The current server exports only `list_ngfws`, which performs EC2
instance discovery through the shared AWS CLI argv-array helpers.

## Architecture Decisions

- Treat `mcp/ngfw` as a least-privilege general MCP surface under ADR-014-R1:
  non-secret, non-mutating observability only.
- `mcp/ngfw/SECURITY.md` must describe the live exported tool surface from
  `mcp/ngfw/index.js`, not historical helper capabilities left in `mcp/ngfw/lib.js`.
- Command-execution internals for removed tools are not active threat-model
  content. If retained at all, they must be explicitly labeled historical or
  deleted from the active NGFW security boundary.
- The doc guard belongs with the existing surface invariant:
  `mcp/ngfw/tool-surface.test.js` is the canonical check that removed PAN-OS
  execution tools and Secrets Manager access are absent.
- Future NGFW tool additions must update the security doc and the surface test
  in the same change. The durable seam is a declared expected tool list in the
  test, derived from `server.tool(...)` registrations, rather than prose-only
  review.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1191 |
| --- | --- | --- |
| MCP registration | `mcp/ngfw/index.js` `server.tool(...)` calls | Document only the exported tools registered here. |
| Tool input shape | `EnvSchema` in `mcp/ngfw/index.js` | Keep `env` as the Zod-validated `dev`/`prod` selector; do not add duplicate schemas in docs or tests. |
| AWS process boundary | `mcp/shared/aws-helpers.js`, re-exported by `mcp/ngfw/lib.js` | Keep AWS calls on argv arrays through `awsJson`; no shell strings or local command execution surface. |
| Credential selection | `PROFILES`, `PANW_SHIFTER_DEV_PROFILE`, `PANW_SHIFTER_PROD_PROFILE`, `getProfile` | Describe these as local AWS profile selection, not authorization or RBAC. |
| Surface hardening | `mcp/ngfw/tool-surface.test.js`, ADR-014-R3 | Extend this test or equivalent enforcement so tool-surface changes require security-doc review. |
| ADR enforcement | ADR-010, ADR-014, `scripts/adr_guard/adr_guard.py` | Preserve argv-array and least-privilege MCP surface rules. |
| CI workflow | `.github/workflows/_quality.yml` `mcp-lint` and `mcp-tests` jobs | Validate with `cd mcp/ngfw && npm test` and lint when JS/test files change. |

## Cross-Cutting Layers

- Auth surface: `mcp/ngfw` has no application actor identity or RBAC layer.
  Therefore the design must remain least-privilege and must not expose privileged
  NGFW administration tools to arbitrary connected MCP clients.
- Secret-handling surface: the active server must not call Secrets Manager or
  return SSH private keys, passwords, tokens, or secret-bearing URLs in MCP
  responses. `tool-surface.test.js` already asserts absent Secrets Manager calls.
- Env-binding shape: `EnvSchema` allows only `dev` or `prod` and defaults to
  `dev`; `PROFILES` maps those values to `PANW_SHIFTER_*_PROFILE`. This selects
  credentials but is not an authorization boundary.
- Config validators: architecture changes must continue to satisfy ADR-010 and
  ADR-014 via `adr_guard`. MCP package changes must satisfy the package-native
  Node test and lint jobs.
- OS/process exposure: `list_ngfws` may invoke `aws` only through
  `mcp/shared/aws-helpers.js` with argv arrays. No token, profile, command body,
  or shell pipeline should be constructed as a process command string.
- Error envelope: the handler currently returns `Error: ${err.message}` in MCP
  text content. Keep errors operation-labeled and non-secret; do not surface
  raw secret values, private keys, shell command bodies, or multiline payloads.

## Extensibility Seam

The extensibility seam is the NGFW tool-surface invariant. Keep a single expected
tool list in `mcp/ngfw/tool-surface.test.js` or an equivalent package-local
guard, and make the test assert that `mcp/ngfw/SECURITY.md` names that guard.
The next legitimate addition, such as another read-only discovery tool, should
require one test list update and one security-doc update, not a new test
framework or duplicated schema.

## Gotchas And Anti-Patterns

- Do not conflate `mcp/ngfw/lib.js` helper exports with active MCP capabilities;
  only `server.tool(...)` registrations define the live tool surface.
- Do not describe `run_command`, `show_system_info`, `show_routes`, SSH key
  retrieval, SSM command forwarding, or PAN-OS CLI execution as active NGFW MCP
  capabilities.
- Do not weaken `tool-surface.test.js` into a loose grep for stale words. The
  useful invariant is exported tools present/absent and no Secrets Manager use.
- Do not add a separate doc parser, schema registry, or policy layer for this
  maintenance issue. Reuse the existing test and ADR guard seams.
- Do not imply that `env=prod` plus an AWS profile is safe for privileged
  operations. The current surface is safe because it is non-mutating discovery,
  not because `EnvSchema` authorizes the caller.
- Do not remove ADR-010 AWS argv-array guidance from the security doc when
  deleting stale PAN-OS command text; `list_ngfws` still crosses the AWS CLI
  process boundary.

## Non-Goals

- No new MCP tools, no PAN-OS administration, no SSM/SSH command path, and no
  Secrets Manager integration.
- No migration from AWS CLI helpers to an AWS SDK.
- No new authorization system, audit framework, config schema, exception
  hierarchy, logging framework, or workflow.
- No ADR change is needed unless the implementation changes the NGFW MCP
  capability class or introduces a new enforcement mechanism.

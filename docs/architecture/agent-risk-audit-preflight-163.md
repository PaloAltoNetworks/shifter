# Agent Risk Audit Preflight (#163)

Status: pre-implementation guidance

Date: 2026-06-24

Issue: GitHub #163, "Automation: agent risk audit"

Architectural authority: ADR-023, "Agent risk audit findings use canonical
internal identity and sanitized public tracking."

This note applies ADR-023 to issue #163 and records issue-specific design
guidance for a repeatable agent-driven risk audit workflow. It is intentionally
not an implementation plan.

## Scope Boundary

Treat this as a risk-governance workflow, not as a scanner framework, remediation
bot, GitHub sync engine, or new Risk Register product.

The Risk Register remains the canonical internal store for detailed findings.
GitHub issues are sanitized tracking proxies for work coordination only. The
workflow may analyze the repository and propose Risk Register / GitHub updates,
but writes to the Risk Register, GitHub issues, severity ratings, confidence
promotion, reopening, closing, or lifecycle changes require an explicit human
review gate.

No autonomous remediation, issue closing, PR creation, workflow dispatch,
infrastructure mutation, production command execution, or broad cloud/API access
is in scope for this issue.

## ADR-023 Decisions Applied

- **One canonical internal risk identity.** Each tracked risk needs a stable
  opaque `risk_key` persisted in the Risk Register and copied verbatim into the
  matching GitHub issue. Database primary keys and GitHub issue numbers are
  useful links, not the risk identity.
- **Same risk is structural, not prose-based.** Dedupe must compare a versioned
  normalized tuple, not titles, descriptions, or model prose.
- **Public issue content is a derived sanitized view.** GitHub issue titles and
  bodies are generated from a public-summary policy, not copied from the Risk
  Register detailed description, attack vector, evidence, logs, or comments.
- **Risk Register schema must carry machine metadata explicitly.** If the
  current `Risk` fields are insufficient, add structured fields or a small link
  table rather than hiding `risk_key`, dedupe fingerprints, component scope,
  confidence, last-seen data, or GitHub links in free-form text.
- **Reuse platform auth.** New automation uses `shared.api_tokens.ApiToken` with
  exact `risk:read` / `risk:write` scopes plus the existing Risk Register Cognito
  group gate. Do not expand the deprecated `risk_register.APIKey` path.
- **Reuse platform audit.** Productized Risk Register mutations should flow
  through the existing Risk Register API/service path and `risk_register.services`
  audit helpers. If the workflow instead stays an operator MCP run using
  `mcp/ops` named DB tools, document that the MCP JSONL audit is the audit
  evidence and that portal `AuditLog` rows are not automatically created by
  direct table writes.
- **GitHub target is fixed by repo config.** All GitHub issue operations target
  `Brad-Edwards/shifter`, the canonical repo in `.ground-control.yaml`, unless a
  user explicitly says otherwise in the current turn.

## Same-Risk Contract

The minimum dedupe unit is a versioned normalized tuple:

| Field | Meaning |
| --- | --- |
| `component_scope` | The major repo/product area, preferably aligned with `.github/quality-path-filters.yaml` categories. |
| `asset_class` | The asset or boundary affected: API endpoint, auth flow, secret store, workflow runner, Terraform module, MCP tool, database table, Kubernetes workload, etc. |
| `risk_kind` | Controlled risk taxonomy such as CWE/OWASP class, STRIDE category, or repo-native control family. |
| `control_failure` | The missing or weak control, stated generically. |
| `actor_vector` | Who can exercise the risk and by what broad path, without exploit steps. |
| `precondition_class` | Required state such as authenticated user, PR author, compromised runner, public internet, operator token, or local repo access. |
| `impact_class` | Broad impact: privilege escalation, credential exposure, data tampering, service outage, audit bypass, etc. |

Two findings are the same risk when this tuple matches under the same
`dedupe_version` and the evidence points to the same control failure. Different
files or instances can be the same risk when they share one control failure.
The same code area can hold multiple risks when the actor, impact, or missing
control differs.

The public GitHub marker should be an opaque key such as:

```text
Risk-Key: SHF-RISK-<opaque-id>
```

Do not publish a raw hash of sensitive evidence or a fingerprint input that
could be dictionary-attacked back to internal details. If a deterministic
fingerprint is needed for matching, keep it internal or derive it only from
non-sensitive normalized values.

## Linking Rules

- Risk Register entry stores `risk_key` and, when linked, the canonical GitHub
  reference (`Brad-Edwards/shifter#NNN` or equivalent structured fields).
- GitHub issue body stores only `Risk-Key: ...` plus a sanitized Risk Register
  reference phrase. It must not include internal URLs, database IDs as the only
  link, exploit evidence, raw scanner output, or private environment details.
- Search order on reruns: exact `risk_key`, then existing GitHub issue marker,
  then internal dedupe fingerprint, then human review for uncertain matches.
- If a previously known closed/resolved risk reappears, the workflow may propose
  a comment or reopen/update action, but it must not reopen or close
  autonomously.

## Confidentiality Red Lines

GitHub issues may include:

- sanitized title;
- broad component;
- broad risk class;
- user/operator impact in non-exploit language;
- `Risk-Key`;
- high-level mitigation objective;
- review/status labels.

GitHub issues must not include:

- exploit steps, proof-of-concept payloads, curl commands, SQL, shell, or SSM
  commands that demonstrate exploitation;
- secrets, tokens, cookies, private keys, auth headers, presigned URLs, or raw
  secret-manager values;
- internal endpoints, hostnames, IPs, account IDs, bucket names, VPC/subnet IDs,
  RDS endpoints, serial numbers, or other live cloud identifiers;
- raw logs, stack traces, provider errors, SSM stdout/stderr, database errors,
  or scanner output;
- detailed line-by-line attack chains where the detail belongs in the internal
  Risk Register entry.

Use `shared.log_sanitize.safe_log_value`, `safe_log_id`, and
`safe_log_fingerprint` for logs. For public text, prefer omission or coarse
classification over redacting after the fact.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Risk model and lifecycle | `risk_register.models.Risk`, `Comment`, `AuditLog`, soft-delete managers | Extend deliberately if metadata is needed; do not overload description/comments as machine state. |
| Risk API validation | `risk_register.api.serializers`, `RiskViewSet`, `CommentViewSet` | Reuse severity/status/STRIDE and 1-5 score validation. Avoid duplicate DTOs. |
| Risk authz | `risk_register.access`, `HasRiskRegisterCognitoGroup`, `IsStaffSessionOrToken`, `require_scope(scopes.RISK_READ, scopes.RISK_WRITE)` | Keep Cognito group plus exact token scopes. |
| Programmatic auth | `shared.api_tokens` model, scopes, admin, auth, permission helpers | Do not introduce a second token model or expand legacy `X-API-Key`. |
| Audit | `risk_register.services.AuditEvent`, `audit_log`, `audit_log_from_request`, `audit_log_system_event`, `get_client_ip`, `get_request_id` | Keep durable audit in the existing store for product/API writes. |
| Operator MCP path | `.shifter.yaml`, `mcp/ops/policy.js`, `mcp/ops/audit.js`, `mcp/ops` named risk tools | If used, keep idempotency keys, env confirmation, session profiles, and sanitized JSONL audit. |
| Logging | `config.logging.ECSFormatter`, `config._logging_config`, `shared.log_sanitize` | Log only safe identifiers, counts, statuses, and fingerprints. |
| Error envelopes | `shared.errors.classify_user_message`, `UserFacingError`, DRF exceptions | Public/API errors must not echo raw scanner or provider exceptions. |
| Component scoping | `.github/quality-path-filters.yaml`, ADR guard path categories | Chunk audits by existing repo categories where possible. |
| GitHub repo identity | `.ground-control.yaml`, `.gc/plan-rules.md`, `mcp/ops/lib.js::DEFAULT_GITHUB_REPO` | Use `Brad-Edwards/shifter`; do not infer from remotes or migrated issue URLs. |
| Architecture gates | `.importlinter`, `scripts/adr_guard/adr_guard.py`, docs under `docs/adr/` | New guardrails or guardrail-file changes require ADR/docs updates. |

## Cross-Cutting Layers

### Security

- **Auth surface:** Risk Register API writes must pass DRF authentication,
  Cognito group authorization, staff/session or scoped-token admission, and
  exact `risk:write` scope. GitHub issue writes need the narrowest issue
  read/write permission available for `Brad-Edwards/shifter`, not repo admin or
  workflow dispatch rights.
- **Secret-handling surface:** detailed findings stay in the Risk Register.
  GitHub receives a sanitized projection. Raw tokens must not appear in argv,
  query strings, generated files, logs, audit JSON, GitHub bodies, or comments.
- **Env-binding shape:** avoid new runtime env knobs unless needed. If added to
  Django settings, use existing config parser patterns and update
  `config/env-manifest.json`. If added to MCP policy, use `.shifter.yaml` and
  its parser/tests rather than ad hoc env flags.
- **Config validators:** Risk fields still pass model/serializer validation;
  token scopes still pass `shared.api_tokens.scopes.validate_scopes`; MCP tools
  still pass Zod schemas and `.shifter.yaml` policy validation; repo changes
  still pass ADR guard.
- **OS/runtime exposure:** repository analysis should be static/read-only by
  default: `rg`, file parsing, dependency metadata, and safe local inspection.
  Do not run `terraform apply`, `kubectl`, `aws`, `gcloud`, SSM, `gh workflow
  run`, migrations, production management commands, or arbitrary project scripts
  as part of risk discovery. Do not place credentials in shell-visible command
  arguments.
- **Error envelope:** scanner/parser failures should produce fixed or sanitized
  status messages. Full tracebacks and raw tool output stay server/operator-side
  and are sanitized before logging.
- **Observability:** every run should have a run id, component scope, repository
  revision, created/updated/no-op counts, and review decisions. Store detailed
  run rationale internally; public issue comments get only sanitized outcomes.

### Maintainability

- Reuse the Risk Register API/service boundary for product code. Use MCP named
  DB tools only for explicit operator workflows.
- Keep severity/status/STRIDE/confidence enums centralized. If MCP risk tools
  need new fields, update their schemas/tests alongside the Django model/API so
  the two surfaces do not drift.
- Keep GitHub issue rendering in one sanitizer/serializer. Do not let each
  component reviewer write public bodies by prompt convention.
- Keep run chunking aligned with existing repo path categories instead of
  inventing a competing component taxonomy.
- Do not create a second exception hierarchy, logging redaction helper,
  API-token store, audit table, or risk schema for automation.

### Extensibility

The required seam is a versioned risk-audit taxonomy plus a public-summary
serializer:

- adding a component should update the component taxonomy, not prompt prose;
- adding a risk class should update the taxonomy/validator, not free-form
  matching logic;
- changing from GitHub issues to another tracker should swap the tracker adapter
  and public-summary renderer without changing Risk Register identity;
- changing the dedupe tuple requires a `dedupe_version` bump and migration or
  compatibility matching strategy.

### Whole-Repo View

Likely in scope for future implementation:

- `shifter/shifter_platform/risk_register/{models,services,admin,views}.py`
- `shifter/shifter_platform/risk_register/api/{serializers,views,permissions,authentication,urls}.py`
- `shifter/shifter_platform/templates/risk_register/**` if metadata becomes UI-visible
- `shifter/shifter_platform/shared/api_tokens/**`
- `shifter/shifter_platform/shared/{log_sanitize,errors}.py`
- `shifter/shifter_platform/config/{settings,_api_token_settings,_env_manifest.py,env-manifest.json,urls.py}` if runtime config changes
- `mcp/ops/{index,lib,policy,audit}.js`, `.shifter.yaml`, and `mcp/ops/*test.js` if the operator MCP path changes
- `.github/quality-path-filters.yaml` only if component chunking becomes an enforced repo taxonomy
- `.ground-control.yaml`, `.gc/plan-rules.md`, and `docs/adr/**` only if guardrails change
- tests under `shifter/shifter_platform/tests/{risk_register,shared,config}` and `mcp/ops/*test.js` for touched surfaces

Usually out of scope:

- Terraform, Kubernetes, Packer, and GitHub Actions workflow changes unless the
  implementation adds a scheduled workflow, runtime secret delivery, or policy
  gate.
- New public docs unless behavior ships to operators/users.
- Changelog fragment for this docs-only preflight; future user-visible or
  automation behavior changes need one.

## Gotchas And Anti-Patterns

- Do not dedupe by title, body text, line number, or GitHub issue title.
- Do not publish a deterministic hash of sensitive evidence into GitHub.
- Do not put detailed exploitability, internal topology, live cloud identifiers,
  or raw scanner output into a public issue.
- Do not treat model confidence as severity. Severity is impact/likelihood;
  confidence is evidence quality.
- Do not file public issues for low-confidence candidates without human
  promotion.
- Do not silently mutate `severity`, `status`, `resolution_reason`, or close /
  reopen issues based on a rerun.
- Do not bypass Risk Register serializers and audit when building a product/API
  feature. Direct DB writes are an operator MCP choice with different audit
  semantics.
- Do not add local per-component validators, duplicate enum lists, or separate
  GitHub body templates.
- Do not broaden tokens, GitHub permissions, `.shifter.yaml` profiles, or
  workflow runner access to make scanning easier.
- Do not let untrusted repository/log/issue text instruct the agent to perform
  writes without the explicit human gate.

## Non-Goals

- No implementation in this preflight note.
- No autonomous remediation, PR creation, branch updates, or code changes.
- No autonomous GitHub issue closing, Risk Register closing, or severity
  downgrades.
- No new scanner framework, SIEM/GRC platform, RBAC model, token system, audit
  store, exception framework, or logging framework.
- No production infrastructure, database, cloud, SSM, Kubernetes, Terraform, or
  workflow mutations during analysis.

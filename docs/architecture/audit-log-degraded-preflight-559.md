# Audit Log Degraded-Health Preflight (#559)

Status: pre-implementation guidance

Date: 2026-06-28

Issue: GitHub #559, "Architecture review: make audit logging durable or
explicitly degraded instead of swallowing failures"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is not an implementation plan.

## Scope Boundary

Treat this as a policy and observability hardening of the existing platform
audit store, not as a new event bus, SIEM exporter, logging framework, or
product workflow.

Keep these concepts separate:

1. Mandatory audit writes that are part of a safety control and must fail
   closed with the mutation they describe.
2. Best-effort audit writes where user traffic may continue but audit health is
   explicitly degraded and machine-visible.
3. Public readiness, which is the `/health` traffic-admission contract.
4. Operator metrics, which are low-cardinality provider-visible signals.
5. Durable audit evidence, which remains the `risk_register.models.AuditLog`
   table and archived audit-log flow.

## Architecture Decisions

- `risk_register.models.AuditLog` remains the canonical durable audit store.
  Do not add a parallel audit table, activity-log replacement, per-app audit
  schema, or duplicate state-change DTO.
- Keep `risk_register.services.audit_log()` as the single write facade for
  app-level audit events. Existing callers should not bypass it by calling
  `AuditLog.log()` directly when changing failure behavior.
- Preserve the existing fail-closed path for security-critical role changes:
  `audit_role_sync()` uses `audit_log(..., strict=True)` and callers rely on
  transaction rollback when audit persistence fails.
- For non-strict audit writes, silent loss is no longer acceptable. A failed
  write may remain best-effort only if it records bounded in-process degraded
  state and exposes that state through an existing machine-visible surface.
- The machine-visible surface should reuse the current health and metrics
  incumbents:
  - `config.health_checks` / `django-health-check` when degraded audit health
    should influence readiness.
  - Provider-aware metric emission patterns from `config.capacity_metrics` when
    audit failure counts or state should be operator-visible without changing
    traffic admission.
- Public `/health` output must stay coarse: check labels plus
  `working` / `unavailable`, never raw database exceptions or audit payloads.
- Audit failure telemetry is about audit subsystem health, not the audited
  entity. Metric labels, health labels, and logs must not include entity state,
  request bodies, tokens, headers, user emails, or arbitrary exception text.
- No new ADR is required for documenting or implementing this within the
  existing `risk_register`, `config.health_checks`, and bounded metric-emitter
  surfaces. A repo-wide audit durability queue, new telemetry platform, or
  changed readiness taxonomy would need separate design/ADR work.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #559 |
| --- | --- | --- |
| Audit write facade | `risk_register.services.AuditEvent`, `audit_log`, `audit_log_from_request`, `audit_log_system_event`, `audit_auth_event`, `audit_session_event` | Extend this facade instead of adding per-view try/except blocks or another audit helper. |
| Mandatory audit safety control | `risk_register.services.audit_role_sync`, `audit_log(..., strict=True)`, `config.user_type_sync.sync_user_type` | Keep fail-closed role/profile changes strict; do not convert them to degraded best-effort. |
| Audit schema and query surface | `risk_register.models.AuditLog`, `AuditLog.Action`, `AuditLog.EntityType`, `risk_register.api.views.AuditLogViewSet`, `AuditLogAdmin` | Add enum/schema changes only if there is a real auditable event, with migrations and existing admin/API visibility. |
| Request attribution | `get_client_ip`, `get_request_id`, `get_actor_from_request`, `RequestAudit` | Preserve trusted XFF semantics and request correlation. Do not duplicate request parsing in callers. |
| Health surface | `config.health.CoarseHealthCheckView`, `config.health_checks`, `health_check.plugins.plugin_dir` | Register any audit-health probe through the existing plugin registry and keep the public response coarse. |
| Metrics surface | `config.capacity_metrics` provider-aware client factory and fail-soft emitter pattern | If metrics are used, keep a narrow audit-health namespace/signals, low-cardinality dimensions, fail-soft emission, and provider-aware publishing. |
| Logging | `config.logging.ECSFormatter`, `config._logging_config`, module loggers | Log bounded, sanitized audit-health transitions and failure counts only. |
| Log sanitization | `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint` | Sanitize exception class/reason summaries and fingerprint sensitive identifiers if correlation is needed. |
| Error envelopes | `shared.errors.classify_user_message`, existing API/view error handling | Do not expose audit persistence details to browser/API clients unless the operation deliberately fails closed with an authored error. |
| Tests | `tests/risk_register/test_audit_services.py`, `tests/mission_control/test_health.py`, `tests/config/test_capacity_metrics.py` | Extend real-boundary tests: real DB failure for audit behavior, coarse health output, and fake metrics clients. Avoid first-party patch seams. |
| Import boundaries | `.importlinter`, public service facades, `shared` helpers | `config` may depend on installed apps at startup as it already does for health checks; do not make app layers import across forbidden boundaries. |
| Architecture enforcement | `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `.importlinter` | Run the Python and architecture checks for touched surfaces; do not weaken guardrails. |

## Cross-Cutting Layers

Security layers the implementation must pass:

- Auth surface: audit health changes must not create public diagnostic or
  operator endpoints. Existing browser session, OIDC, Identity Platform, DRF,
  API-token, dev-login, CSRF, and CTF magic-link gates remain unchanged.
- Authorization surface: audit degradation must not become an authorization
  bypass. If a path is classified as mandatory audit, the domain mutation fails
  closed when the audit write fails.
- Secret-handling surface: audit `previous_state` / `new_state`, request
  headers, cookies, Authorization values, ID tokens, API keys, Guacamole URLs,
  DB/Redis URLs, secret references as values, and full exception strings must
  not be copied into logs, metric dimensions, health bodies, command lines, or
  client error envelopes.
- Env-binding shape: any new non-secret knob belongs in Django settings using
  the existing `_env_*` or split-settings pattern and must be reflected in
  runtime env renderers only if deployment needs to configure it. Raw audit
  payloads or credentials must never become env values.
- Config validators: Python changes under `shifter/shifter_platform` must pass
  ruff; import changes must pass `.importlinter`; architecture changes must pass
  ADR guard. Terraform/Kubernetes checks apply only if runtime/deploy surfaces
  are edited.
- OS/runtime exposure: do not shell out from request paths or metric emitters,
  do not pass audit details in process argv, do not dump env or database errors,
  and do not write fallback audit payloads to local files unless a separate
  durable-queue design owns permissions, retention, encryption, and replay.
- Error-envelope surface: non-strict audit failures should not alter successful
  user responses. Strict paths should fail with existing fixed/sanitized error
  envelopes, not raw database or JSON serialization exceptions.
- Public health surface: if audit health is added to `/health`, it must use the
  existing `django-health-check` plugin shape and preserve coarse output
  (`working` / `unavailable`) plus non-sensitive plugin labels.

Maintainability incumbents the implementation must build on:

- `risk_register.services` for all audit write policy, request context, strict
  vs non-strict behavior, and audit-health state updates.
- `risk_register.models.AuditLog` for durable audit rows and existing archive
  behavior.
- `config.health_checks` and `CoarseHealthCheckView` for readiness/degraded
  health.
- `config.capacity_metrics` patterns for provider-aware, fail-soft metric
  publishing if metrics are added.
- `shared.log_sanitize` and ECS logging for log hygiene.
- Existing tests under `tests/risk_register`, `tests/mission_control`, and
  `tests/config` for real-boundary coverage.

Extensibility seam:

The durable seam is an audit failure policy plus audit-health signal owned by
`risk_register.services`:

- policy: `strict` fail-closed vs explicit degraded best-effort;
- degraded state: last failure time, failure count/window, and last sanitized
  failure class or reason category;
- signal consumer: readiness, metric, log-only plus metric, or future durable
  queue;
- reset semantics: what successful write or operator action returns audit
  health to working;
- scope: process-local, database-backed, cache-backed, or future durable queue.

The next likely variation is a durable retry queue for non-strict audit writes.
Leave the policy boundary parameterized so that adding a queue later changes the
audit writer internals and health probe, not every app-level audit caller.

## Whole-Repo Scope

Likely in scope for the implementation that follows:

- `shifter/shifter_platform/risk_register/services.py`
- `shifter/shifter_platform/risk_register/models.py` and migrations only if
  audit schema or enum vocabulary changes
- `shifter/shifter_platform/config/health_checks.py` and
  `config.health.CoarseHealthCheckView` if degraded audit health affects
  readiness
- `shifter/shifter_platform/config/capacity_metrics.py`,
  `config/capacity_metrics_gcp.py`, and `_capacity_settings.py` only if metrics
  are extended rather than implemented as a narrow new audit-health emitter
- `shifter/shifter_platform/config/settings.py`,
  `config/env-manifest.json`, and runtime env renderers only if new deploy-time
  knobs are introduced
- tests under `shifter/shifter_platform/tests/risk_register`,
  `tests/mission_control`, `tests/config`, and integration tests for any caller
  whose mutation must become fail-closed
- docs under `docs/architecture` or `docs/adr` only if the implementation
  changes repo-wide audit durability, health taxonomy, or guardrails

Usually out of scope:

- Replacing `AuditLog` with a queue or event stream.
- Retrofitting every old direct `AuditLog.log()` caller unless touched behavior
  depends on it.
- Changing auth, RBAC, API-token, OIDC, Identity Platform, CTF magic-link, or
  dev-login semantics.
- Adding a public diagnostics endpoint, Prometheus/statsd stack, SIEM exporter,
  or new operator UI.
- Changing Terraform, Kubernetes, ALB, Docker health checks, or autoscaling
  unless the chosen machine-visible signal requires deploy-time wiring.

## Gotchas And Anti-Patterns

- Do not document "best effort" by leaving the old catch-all `except` with only
  `logger.exception(...)` and `return None`.
- Do not make every audit write strict. Some audit failures should not block
  user traffic; classify the policy at the audit facade and keep high-volume
  flows available with explicit degradation.
- Do not make role-sync or other safety-control audit paths best-effort.
- Do not confuse database health with audit health. The audit writer can fail
  because of JSON serialization, schema constraints, bad enum values, or model
  validation even when the database probe is working.
- Do not expose raw failure details on `/health`; health consumers need a
  machine-visible state, not stack traces or payload values.
- Do not add high-cardinality metric dimensions such as user id, entity id,
  request id, path, action context, exception text, queue URL, or host name.
- Do not catch broad exceptions in callers around audit writes. Centralize
  failure policy so behavior is consistent.
- Do not store sensitive audit payloads in fallback files, cache entries, metric
  labels, or logs to prove that loss did not happen.
- Do not weaken ADR guard, import-linter, ruff, actionlint, TFLint, kube-linter,
  or kubeconform to land observability changes.

## Non-Goals

- No implementation in this preflight note.
- No formal Ground Control requirement or traceability work.
- No new ADR unless the implementation changes repo-wide audit durability,
  health taxonomy, telemetry platform, or architecture guardrails.
- No decision to build a durable queue in this issue. A queue is a future
  escalation if explicit degraded best-effort is not sufficient.
- No historic repair of already-missed audit rows or old audit archive behavior.

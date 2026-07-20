# Setup Orchestrator Output Masking Preflight (#418)

Status: pre-implementation guidance

Date: 2026-06-28

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/418>

This issue is requirement-free. The GitHub issue title and body are the
shipping contract.

## Scope Boundary

Issue #418 is a secret-log hygiene fix for setup command output. The
implementation must ensure known secret values, including `DC_DOMAIN_PASSWORD`,
do not appear in `SetupOrchestrator` stdout/stderr log lines.

In scope:

- `SetupOrchestrator`-owned logging of `CommandResult.stdout` and
  `CommandResult.stderr`, including success, failure, verification, retry, and
  PAN-OS commit/poll paths.
- The existing setup-plan context values that can contain secrets, especially
  `domain_admin_password`, `dsrm_password`, and `rdp_password`.
- Tests that prove both environment-sourced and context-sourced secrets are
  absent from captured logs.

Out of scope unless needed to close a proven leak on the setup path:

- Changing `CommandResult`, `StepResult`, `SetupResult`, executor return
  values, retry semantics, or setup plan behavior.
- Changing how domain, RDP, or DC credentials are generated, fetched, stored, or
  passed to SSM/SSH.
- Reworking platform-wide logging, ECS JSON formatting, audit logging, or
  Django error envelopes.

## Architecture Decisions

- Reuse the provisioner setup logging seam. The canonical owner for output
  masking is `_SetupOrchestratorLoggingMixin` under
  `shifter/engine/provisioner/orchestrators/_setup_logging.py`, re-exported
  through `SetupOrchestrator`; do not add a second redaction utility elsewhere.
- Mask only at log sinks. `CommandResult.stdout/stderr` and
  `StepResult.stdout/stderr` remain raw operational data for parsers such as
  PAN-OS job handling. The invariant is that raw streams are never logged
  without passing the setup-output masker.
- Known secret values come from two inputs: named env vars such as
  `DC_DOMAIN_PASSWORD`, and setup context keys whose names indicate secret
  material. Keep those allowlists centralized on the setup logging mixin.
- Output masking is not a substitute for log-value sanitization. Opaque IDs,
  exception summaries, paths, hostnames, and other non-secret/user-controlled
  values should continue to use `log_redact.safe_log_value`,
  `safe_log_id`, or `safe_log_fingerprint` as appropriate.
- Executor debug logs are a separate leak surface. If an executor used by
  `SetupOrchestrator` logs raw command text or command output before returning
  a `CommandResult`, the implementation must remove that content logging or
  route it through the same masking seam without giving the executor a new
  domain-specific secret model.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #418 |
| --- | --- | --- |
| Setup output logging | `_SetupOrchestratorLoggingMixin._log_step_success`, `_log_step_failure`, and `_mask_sensitive_output` | All `SetupOrchestrator` stdout/stderr log lines pass through this path. Do not add per-call `replace()` logic. |
| Secret source list | `_SetupOrchestratorLoggingMixin.SENSITIVE_ENV_VARS` and `SENSITIVE_CONTEXT_KEY_PARTS` | Add names or key heuristics here only. Keep ordering longest-first to prevent partial replacement artifacts. |
| Runtime contracts | `executors.base.CommandResult`, `orchestrators._setup_types.StepResult`, `SetupResult`, `SetupError` | Preserve raw return payloads and existing failure asymmetry: transport/PAN-OS hard failures raise, exit-nonzero exhaustion returns a failed `StepResult`. |
| Plan context ownership | `SetupPlan.get_context()` in `plans/dc_setup.py`, `plans/domain_join.py`, and `plans/set_local_password.py` | Reuse existing context keys; do not add parallel DTOs or schemas just to identify secret values. |
| Secret transport | `DC_DOMAIN_PASSWORD` task env, AWS SSM SecureString substitution for per-instance RDP passwords, provider secret stores for GCP/GDC | Do not move secrets into process argv, user data, Terraform output logs, or generated docs. |
| Provisioner log sanitization | `shifter/engine/provisioner/log_redact.py` | Use it for non-secret log-injection safety and identifier fingerprinting. It does not replace value masking for actual stdout/stderr secret material. |
| Platform log sanitization | `shifter/shifter_platform/shared/log_sanitize.py` and `config.logging.ECSFormatter` | Platform/Django logs keep their existing sanitizer and formatter; do not import platform logging helpers into the provisioner. |
| Existing tests | `shifter/engine/provisioner/tests/test_setup_orchestrator.py` and `tests/test_log_redact.py` | Extend the local provisioner test suite. Do not create a new top-level test harness. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: none. This is an engine-provisioner internal runtime path, not a
  user-facing request path. Do not change Django auth, range ownership checks,
  GitHub OIDC, or IAM policy to solve a log-sink problem.
- Secret-handling surface: `DC_DOMAIN_PASSWORD` remains a deployment-scoped env
  secret forwarded to the provisioner; domain join/DC setup context keys remain
  owned by their plans; per-instance RDP password setup keeps the #762
  SSM SecureString/provider-secret-store path. The output masker must cover any
  of these values if a script echoes them.
- Env-binding shape: keep the env var names centralized in
  `SENSITIVE_ENV_VARS`. Do not introduce a new runtime setting, manifest key,
  YAML config, or Terraform variable for the redaction list unless a future
  requirement needs operator configuration.
- Runtime validation gates: `SetupOrchestrator._render_script` still validates
  missing template variables with `SetupError`; plan `get_context()` methods
  still validate required secret-bearing keys. The masking change must not
  loosen those validators or catch-and-hide their failures.
- OS/process exposure: setup plans must continue avoiding passwords in command
  argv where existing tests enforce it. AWS per-instance passwords should remain
  `{{ssm-secure:...}}` substitutions; GCP/GDC fetched secrets should stay in
  process memory and stdin/script bodies only where the existing plan already
  requires it.
- Error envelopes: `SetupError` messages and exception logs must not include
  raw stdout, stderr, rendered scripts, or secret values. Preserve existing
  exception types instead of creating a masking-specific exception hierarchy.
- Observability: logs may include step name, attempt count, exit code, byte
  counts, command IDs, and sanitized/fingerprinted identifiers. They must not
  include raw secret values, rendered secret-bearing scripts, or command output
  before setup-output masking.
- Workflow and static checks: provisioner Python changes should use the package
  Ruff/pytest surface and the repo ADR guard. Guardrail, workflow, ADR, or
  import-boundary edits would bring the corresponding repo-level validators
  into scope.

## Extensibility View

The only extension seam needed now is the sensitive-value provider on the setup
logging mixin:

- env-var names: extend `SENSITIVE_ENV_VARS`;
- context-key heuristics: extend `SENSITIVE_CONTEXT_KEY_PARTS`;
- future one-off values not present in env/context: add a narrow optional
  `extra_sensitive_values` parameter to the mixin-level masking call, not a
  new global logging framework.

This keeps the next obvious change, such as masking a new provider token or
temporary setup credential, local to the setup logging boundary.

## Whole-Repo Surfaces In Scope

- `shifter/engine/provisioner/orchestrators/setup_orchestrator.py`
- `shifter/engine/provisioner/orchestrators/_setup_logging.py`
- `shifter/engine/provisioner/orchestrators/_setup_panos.py`
- `shifter/engine/provisioner/orchestrators/_setup_types.py`
- `shifter/engine/provisioner/executors/base.py`
- `shifter/engine/provisioner/executors/ssm_executor.py`
- `shifter/engine/provisioner/executors/ssh_executor.py`
- `shifter/engine/provisioner/executors/guest_ssh_executor.py`
- `shifter/engine/provisioner/executors/ngfw_executor.py`
- `shifter/engine/provisioner/plans/dc_setup.py`
- `shifter/engine/provisioner/plans/domain_join.py`
- `shifter/engine/provisioner/plans/set_local_password.py`
- `shifter/engine/provisioner/log_redact.py`
- `shifter/engine/provisioner/tests/`
- `shifter/shifter_platform/shared/log_sanitize.py` and platform logging config
  only as comparison surfaces, not implementation targets

## Gotchas And Anti-Patterns

- Do not redact only success logs. Failure, retry, verification, PAN-OS commit
  failure, and poll output paths are equally log-visible.
- Do not mask by secret variable name alone. The leaked output contains secret
  values, not necessarily the variable names.
- Do not rely on `safe_log_value` for secret values. It escapes control
  characters but intentionally does not hide the value or break every
  clear-text-secret taint flow.
- Do not log rendered scripts, `stdin_input`, or full command bodies while
  trying to debug redaction.
- Do not put masking in each plan. Plans own setup intent and context
  validation; the orchestrator owns logging of execution output.
- Do not mutate raw `CommandResult`/`StepResult` payloads unless a later issue
  explicitly changes the artifact-retention contract.
- Do not create a provisioner-to-platform import just to share
  `shared.log_sanitize`; the provisioner already has `log_redact`.
- Do not add broad regexes that redact ordinary status words, hostnames, or
  IDs. Prefer exact secret values from env/context so logs remain useful.

## Non-Goals

- No new ADR is needed for this issue.
- No schema, database, API, controller, repository, or persistence change is
  needed.
- No change to credential generation, rotation, storage, or retrieval is in
  scope.
- No CI/workflow weakening, lint suppression, or test skip is acceptable.
- No generic secret-scanning framework or platform-wide logging wrapper should
  be introduced for this narrow setup-output log sink.

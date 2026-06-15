# Provisioner Plan Template Lint Preflight

Issue: GitHub #616, "Lint provisioner plan scripts for unrendered
{{word}} tokens".

This note records the architecture boundary for the future implementation. It
is intentionally not an implementation plan.

## Decision

The check belongs in the provisioner quality surface, preferably as a pytest
static test under `shifter/engine/provisioner/tests/`, and must be run by the
existing provisioner test job. It should catch the same missing-placeholder
failure that `SetupOrchestrator._render_script` would raise at live provisioning
time, without changing range execution behavior as part of this issue.

The runtime contract is the current placeholder matcher:

```text
\{\{\s*(\w+)\s*\}\}
```

Dot-prefixed Docker/Go template fields such as `{{.Names}}` and function calls
such as `{{json .NetworkSettings.Networks}}` remain safe by construction
because they do not match that pattern. Bare word-only tokens such as `{{end}}`,
`{{range}}`, and `{{word}}` do match and must be treated as provisioner template
placeholders unless declared by the plan context.

The static check should cover every rendered field that can flow through
`SetupOrchestrator`: `SetupStep.script`, `SetupStep.stdin_input`, and
`verify_step` in addition to normal `steps`. The issue text calls out scripts,
but `stdin_input` is rendered by the same runtime method and should not remain a
blind spot.

Plan context keys remain owned by each plan's existing `get_context()` contract.
As shipped, the lint derives the keys directly from `get_context()` for every
plan style — literal-return, loop-built dict, and input pass-through — by
collecting the string literals that appear in a context-key position inside the
method (dict-literal keys, subscript indices, `.get()` arguments, and elements of
a literal list/set/tuple it iterates). This avoids a second per-plan validation
schema and avoids any class-level key declaration: the existing `get_context()`
body is the single source of truth. The lint never instantiates a plan or
executes a script.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Runtime rendering | `SetupOrchestrator._render_script` | The lint semantics must match this regex exactly unless the runtime renderer is intentionally changed in the same future implementation. |
| Plan shape | `SetupPlan` and `SetupStep` in `shifter/engine/provisioner/plans/base.py` | Scan only fields that are rendered by the setup orchestrator. Do not conflate operation plans or executor params with setup script templates. |
| Context validation | Existing `get_context()` methods in `shifter/engine/provisioner/plans/*.py` | Reuse the per-plan context contract. Derive keys from the `get_context()` body itself; do not add a parallel schema or per-plan key declaration. |
| Provisioner tests | `shifter/engine/provisioner/pytest.ini` and `tests/test_*.py` | Keep the check in the provisioner pytest suite so `.github/workflows/_quality.yml` already runs it in `shifter-engine-tests`. |
| CI quality gates | `provisioner-lint`, `provisioner-sast`, and `shifter-engine-tests` in `.github/workflows/_quality.yml` | Do not weaken lint, SAST, coverage, or the `skip_tests` contract to land the check. |
| Secret output masking | `SetupOrchestrator._mask_sensitive_output`, `SENSITIVE_CONTEXT_KEY_PARTS`, and `SENSITIVE_ENV_VARS` | Lint failures may name paths, classes, steps, fields, and token names. They must not print context values or full rendered scripts. |
| Polaris context | `scenario-dev/polaris/lessons-3.md` and `PolarisRangeBootstrapPlan` | Use the lesson note as historical context, not as a new source of enforcement. The enforcement source is provisioner code and tests. |

## Cross-Cutting Layers

Security layers the design must satisfy:

- Auth surface: none. This is repository/CI validation, not a user-triggered
  request path.
- Runtime validation gate: `SetupOrchestrator._render_script` remains the live
  gate that raises `SetupError` for missing placeholders. The static check must
  mirror or import the same matcher; it must not define looser syntax.
- Context shape validation: plan-specific `get_context()` methods remain the
  context contract. The lint should compare placeholder names against that
  declared or inferred key set, not against ad hoc values built inside the test.
- Secret handling: test fixtures must use synthetic dummy values only when
  context construction is needed. Failure messages should identify the missing
  token, plan class, step name, rendered field, and source path, but should not
  echo raw context values, command bodies, passwords, tokens, or presigned URLs.
- OS/process exposure: the check must be static Python/pytest logic. It should
  not execute plan scripts, invoke Docker, open SSM/SSH sessions, or pass script
  bodies through shell argv.
- Error envelopes and logs: provisioner runtime errors continue through
  `SetupError`; pytest failures can be precise but should stay bounded to
  metadata and token names. Do not add a new exception hierarchy for the linter.
- Config and workflow validators: if the future implementation edits
  `.github/workflows/_quality.yml`, it must pass `actionlint` and ADR guard. If
  it only adds provisioner tests or minimal renderer constants, the relevant
  local gates are provisioner ruff/format and provisioner pytest.

Maintainability incumbents the implementation must build on:

- `SetupOrchestrator._render_script` for placeholder matching.
- `SetupStep` fields for the rendered surface.
- Existing plan `get_context()` methods for context ownership.
- Existing per-plan tests that already validate missing context keys with
  `ValueError`.
- Existing `.github/workflows/_quality.yml` provisioner jobs instead of a new
  top-level CI path.

Extensibility seam:

Keep the placeholder matcher and rendered-field list centralized. A future
change should be able to add another rendered `SetupStep` field, another plan
module glob, or a small diagnostic keyword set without rewriting the scan
logic. If explicit context metadata is needed, put the seam on the plan class as
an optional static key set; avoid an external allowlist keyed by filenames.

Whole-repo surfaces in scope for the future implementation:

- `shifter/engine/provisioner/orchestrators/setup_orchestrator.py`
- `shifter/engine/provisioner/plans/base.py`
- `shifter/engine/provisioner/plans/*.py`
- `shifter/engine/provisioner/tests/`
- `shifter/engine/provisioner/pytest.ini`
- `shifter/engine/provisioner/pyproject.toml` and `uv.lock` only if dependencies
  are changed, which should not be necessary for this check
- `.github/workflows/_quality.yml` only if the existing provisioner test job does
  not pick up the new test automatically
- `docs/adr/**`, `scripts/adr_guard/**`, and workflow guardrails only if the
  future implementation changes enforcement policy rather than adding a normal
  provisioner test

## Gotchas And Anti-Patterns

- Comments inside triple-quoted plan scripts are rendered too. A comment that
  contains `{{end}}` is still a real runtime failure.
- Heredoc bodies and generated shell script text are rendered too; do not treat
  quoted heredoc delimiters as a reason to skip scanning.
- `{{range .Containers}}` is safe because it does not match the current regex;
  `{{range}}` and `{{end}}` are not safe.
- `stdin_input` is not optional from an architecture view. NGFW plans already
  use it, and the orchestrator renders it with the same method.
- Do not scan every double-brace occurrence in arbitrary module prose or tests.
  The target is strings that flow into `SetupStep` rendered fields.
- Do not switch the provisioner renderer to Jinja2, alter template syntax, or
  silently allow Go template keywords as a shortcut for this issue.
- Do not add per-file skip lists, xfails, or broad allowlists for known bad
  tokens. Fix the plan script shape or declare the legitimate context key.
- Do not duplicate every plan's context validation in a parallel schema when
  `get_context()` already owns the validation.
- Do not log full script bodies in CI failures; they can include command text
  and placeholders for sensitive values.

## Non-Goals

- Rewriting `SetupOrchestrator._render_script` semantics.
- Rewriting provisioner plan scripts beyond whatever the future lint failure
  forces.
- Validating shell, PowerShell, PAN-OS, Docker, or Go template syntax generally.
- Solving shell injection or quoting for context values; that remains the
  responsibility of existing plan context validation and script authoring.
- Adding a new top-level linter framework, ADR guard check, or Ground Control
  requirement for this requirement-free maintenance issue.

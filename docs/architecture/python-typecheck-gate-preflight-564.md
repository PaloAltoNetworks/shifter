# Python Type-Check Gate Preflight (#564)

Status: pre-implementation guidance

Date: 2026-06-30

Issue: GitHub #564, "Architecture review: promote Python type checking from
advisory signal to enforceable quality gate."

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

This is a repository quality-gate change, not a runtime feature. The
implementation should promote a clearly scoped Python type-check surface from
advisory telemetry to a blocking CI signal while leaving legacy or lower-signal
areas explicitly transitional.

Keep these concepts separate:

1. Blocking type-check scope: the modules/packages that must pass mypy and can
   fail Quality.
2. Transitional type-check scope: legacy areas that may remain permissive or
   advisory, but only behind an explicit boundary.
3. Type-check strictness policy: package-local mypy configuration and overrides.
4. Workflow orchestration: `_quality.yml`, path filters, PR Gate, and local
   pre-commit wiring.
5. Runtime validation and behavior: Django settings, schema validation,
   service boundaries, persistence, logging, and error envelopes must not
   change just to make mypy pass.

## Architecture Decisions

- Reuse the two existing CI type-check surfaces:
  `shifter-platform-typecheck` and `provisioner-typecheck` in
  `.github/workflows/_quality.yml`. Do not add a parallel type-check framework
  or a root workflow that re-invents Quality path routing.
- Keep type-check policy near the Python packages in
  `shifter/shifter_platform/pyproject.toml` and
  `shifter/engine/provisioner/pyproject.toml`. Workflow YAML should invoke the
  policy; it should not become the only place that knows which modules are
  enforced.
- The blocking command must fail normally. Removing only `|| true` or only
  `continue-on-error: true` is not enough; the blocking scope must have neither
  failure-swallowing mechanism.
- A transitional/advisory surface is acceptable only if it is visibly named as
  advisory and cannot satisfy the blocking acceptance criteria by itself.
- The blocking type-check gate should behave like a quality/lint guardrail, not
  like an optional unit-test suite. If it remains conditioned on
  `skip_tests`, the implementation must preserve the protected caller contract
  that passes `skip_tests: false`; the cleaner steady-state is for the
  blocking mypy gate to run whenever its path category runs.
- Do not relax runtime settings validation, schema contracts, import
  boundaries, or secret-handling code to quiet type errors. Fix typing at the
  package boundary, add precise stubs/types where needed, or leave the module
  in the explicit transitional scope.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #564 |
| --- | --- | --- |
| CI type checking | `.github/workflows/_quality.yml` `shifter-platform-typecheck` and `provisioner-typecheck` | Promote these surfaces or split them into enforced/advisory jobs without creating a third orchestration path. |
| Quality path routing | `.github/quality-path-filters.yaml`; `.github/workflows/deploy.yml` `quality_relevant`; PR Gate | Keep changed-path routing centralized. Workflow changes already force the full Quality matrix through `ci_workflows`. |
| Local developer gate | `.pre-commit-config.yaml` `mypy-shifter-platform` and `mypy-provisioner` | Keep local and CI scope aligned. If commands diverge, the divergence must be intentional and documented in the policy surface. |
| Platform mypy policy | `shifter/shifter_platform/pyproject.toml` with `mypy_django_plugin`, `mypy_path = ".."`, `exclude`, and overrides | Preserve Django plugin setup and the `cyberscript` import path. Use overrides or a declared target surface rather than workflow-only module lists. |
| Provisioner mypy policy | `shifter/engine/provisioner/pyproject.toml` `[tool.mypy]` | Keep provisioner typing policy package-local and separate from platform/Django assumptions. |
| Tooling env defaults | `shifter/shifter_platform/config/_runtime_env.py` `_TOOLING_INVOKERS`, `required_runtime_env()`, `require_environment()` | Mypy is already allowed to use explicit non-production defaults. Do not feed live secrets or weaken fail-closed settings import rules. |
| Architecture enforcement | `scripts/adr_guard/adr_guard.py`, `docs/adr/README.md`, ADR enforcement docs | If the implementation turns the type-check policy into an ADR-named invariant, extend the existing ADR guard/workflow-as-data model instead of ad hoc greps. |
| Dependency/runtime management | Package `uv.lock` files and `uv sync --group dev` in Quality jobs | Keep mypy versions and dependencies package-owned. Do not install arbitrary tooling globally in workflow steps. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- GitHub auth surface: type-check jobs run on GitHub-hosted `ubuntu-latest`
  runners with `permissions: contents: read`. They must not request
  `id-token: write`, cloud secrets, GitHub Environments, write scopes,
  `pull_request_target`, or self-hosted runners.
- Secret-handling surface: type checking should use synthetic test/build
  values only when settings import requires them. No AWS/GCP tokens, Django
  production secrets, OIDC client secrets, rendered tfvars, or provider
  credentials belong in mypy env, process argv, logs, or summaries.
- Env-binding and config validators: platform settings already pass through
  `config._runtime_env` and the settings helpers in `config.settings`.
  Preserve `required_runtime_env()`, `require_environment()`,
  `DJANGO_SECRET_KEY` handling, and field-encryption defaults; do not replace
  them with mypy-specific bypasses.
- Config-shape layer: package `pyproject.toml` files are the mypy config
  parser boundary. Avoid duplicate or conflicting policy in workflow comments,
  shell globs, and pre-commit hooks. If a root config is introduced, prove it
  is discovered from every existing package working directory.
- Workflow-policy layer: `actionlint` owns syntax, PR Gate owns aggregate
  branch-protection status, and ADR guard owns repository architecture rules.
  A blocking mypy job should fail through normal GitHub Actions job failure.
- OS/process exposure: keep commands fixed and boring, such as `uv run mypy`
  from the package directory. Do not pass secret-bearing values through shell
  argv, enable `set -x`, echo environment dumps, or generate temporary config
  outside the runner workspace.
- Error and observability surface: failure output should be mypy's normal
  file/line/error-code diagnostics. Do not hide failure behind notices, custom
  summaries, swallowed exits, or broad warning annotations.

Maintainability incumbents the implementation must build on:

- `_quality.yml` type-check jobs and the existing `uv sync --group dev` /
  `uv run mypy` command shape.
- `.pre-commit-config.yaml` mypy hooks, with any changed scope kept consistent
  with CI.
- `shifter/shifter_platform/pyproject.toml` and
  `shifter/engine/provisioner/pyproject.toml` as the durable policy surfaces.
- `config._runtime_env` as the platform settings-import compatibility layer
  for tooling.
- `.github/quality-path-filters.yaml` and `deploy.yml` as the path-routing and
  PR Gate context.
- ADR guard, import-linter, Ruff, Bandit, gitleaks, Terraform, and Kubernetes
  checks as existing hard or documented advisory guardrails that must not be
  weakened to land type-checking.

Extensibility seam:

The seam is the declared enforced scope per package: a package-local target
list, mypy `files` setting, or equivalently explicit package-local policy that
CI and pre-commit both invoke. Future expansion should add modules to that
single scope and tighten overrides there, not add scattered workflow shell
lists or another ad hoc job family. Optional full-tree telemetry, if kept,
must remain separately named advisory.

## Whole-Repo Scope

In scope for implementation:

- `.github/workflows/_quality.yml`
- `.github/quality-path-filters.yaml` only if new or moved policy files must
  trigger the relevant type-check jobs
- `.pre-commit-config.yaml`
- `shifter/shifter_platform/pyproject.toml`
- `shifter/engine/provisioner/pyproject.toml`
- `shifter/shifter_platform/config/_runtime_env.py` only if a real tooling
  import gap remains after reusing the existing mypy invoker support
- `docs/adr/index.yaml`, `docs/adr/README.md`, and ADR enforcement docs only
  if a new ADR-owned guardrail is added
- `scripts/adr_guard/**` only if the implementation adds semantic regression
  checks for the workflow/policy invariant
- `changelog.d/` if the repo's release-note policy requires recording CI
  guardrail changes

Out of scope unless mypy exposes an actual product bug:

- Django model schema changes, migrations, repositories, DTOs, serializers, or
  service-boundary redesign
- New validation frameworks, exception hierarchies, logging frameworks, or
  error-envelope formats
- Runtime auth, OIDC, API token, cloud IAM, Terraform, Kubernetes, or
  persistence behavior
- Broad typing cleanup outside the declared enforced scope
- Ground Control requirement creation or traceability links; #564 is the
  authoritative contract

## Gotchas And Anti-Patterns

- Do not leave `continue-on-error: true` on the blocking job.
- Do not leave `|| true`, `if: always()`, or a post-step notice that converts a
  failed mypy run into a successful job.
- Do not satisfy the issue with comments saying "permissive" or
  "transitional"; the enforced/transitional boundary must be machine-readable
  or otherwise durable enough for CI and local hooks to invoke consistently.
- Do not hide failures by widening `exclude`, adding blanket
  `ignore_errors = true`, dropping the Django mypy plugin, removing
  `warn_unused_ignores`, or switching imports to `Any` at package boundaries.
- Do not conflate all Python packages in the repo with the current mypy estate.
  Other Python package roots can be brought in later, but only with package
  dependencies, path filters, and policy surfaces that match their ownership.
- Do not put a long module allowlist in `_quality.yml` while pre-commit and
  `pyproject.toml` enforce a different list.
- Do not weaken import-linter or cross-layer rules to make mypy imports easier;
  non-`shared` platform layers still must not import `cyberscript` directly.
- Do not create a custom type-check wrapper unless it removes real duplication
  and becomes the single invoked command for both CI and local hooks.

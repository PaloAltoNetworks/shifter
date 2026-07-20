# Workflow Gating Test Suite Preflight (#921)

Status: pre-implementation guidance

Date: 2026-06-14

Issue: GitHub #921, "test: workflow-gating test suite for deploy.yml
(catches #781-class defects)".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Implementation outcome (post-consolidation)

The first cut shipped a standalone `scripts/workflow_gating/` suite plus a
dedicated Quality job. During the PR, `origin/dev` merged a sibling
deploy-workflow-security suite (#935, `test_deploy_workflow_security.py`) that
asserted the same runner-exposure and PR-routing invariants by substring. To
avoid two homes and two parsers, the verification was consolidated onto **one
workflow-as-data model living in `scripts/adr_guard/adr_guard.py`** (the `_dw_*`
helpers: a YAML loader and a constrained `if:` expression evaluator). On that
model:

- The runner-exposure invariant is promoted to a **hard adr_guard check**,
  `deploy-workflow-runner-exposure`, wired to **ADR-003-R5** (which already
  mandated it but had no check). It runs in `adr-conformance` (CI) and the
  `fast` pre-commit profile.
- The remaining invariants (#781 upstream gating, #892 routing matrix, #913
  change-filter split) plus #935's GitHub-Environment binding and ECR-digest
  checks are a single consolidated suite,
  `scripts/adr_guard/tests/test_deploy_workflow.py`, run by the existing
  `Tests (adr_guard)` job. The standalone `scripts/workflow_gating/` package,
  its Quality job, and `test_deploy_workflow_security.py` were removed.

## Scope Boundary

Treat this as deploy-control-plane verification, not as a deploy behavior
change. The suite should read the GitHub Actions workflows as data and assert
that the existing branch/event routing, path filters, job dependencies, runner
exposure rules, and deploy permissions keep their intended shape.

Keep these concepts separate:

1. Workflow syntax validity: `actionlint` owns this.
2. Architecture invariants: `adr_guard` owns repo-wide ADR checks such as
   deploy plan scope and fail-loud deploy verification.
3. Workflow gating behavior: this issue should cover branch/event/path/job
   reachability that syntax lint and narrow ADR checks cannot infer.
4. Cloud deployment verification: reusable deploy workflows own Terraform,
   OIDC, ECS, SSM, GCP, and Kubernetes runtime checks.

Do not make the new suite perform cloud calls, execute GitHub Actions jobs, or
replace the deploy workflows' runtime verification.

## Architecture Decisions

- Use a YAML loader to parse `.github/workflows/deploy.yml` and the reusable
  workflows. Do not validate `if:` guards or `dorny/paths-filter` blocks with
  ad hoc line greps.
- Model GitHub event and branch inputs explicitly. A test case should be able
  to say "pull_request targeting aws-dev" or "workflow_dispatch on main" and
  evaluate the same named workflow outputs and job gates the workflow uses.
- Preserve `deploy.yml` as the single source of branch/event/path routing.
  Reusable workflow tests may inspect callee runner labels and inputs, but they
  should not introduce an alternate deploy router.
- Upstream deploy dependencies must fail closed. For deploy jobs that can run
  after `always()`, an upstream deploy dependency is acceptable only when its
  result is `success` or `skipped`; `failure`, `cancelled`, and absent checks
  are not equivalent to "blocked correctly".
- Pull requests must not reach deploy jobs that run on `self-hosted`. Plan-only
  PR paths may validate static infrastructure intent, but no PR event should
  gain a path to a job that assumes privileged runner, cloud, or environment
  access.
- Every assertion should name the finding or issue it guards, such as #781,
  #892, #913, the runner-exposure fix, TEST-1, or DP-2. Failure messages are
  part of the maintenance surface.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #921 |
| --- | --- | --- |
| Deploy orchestration | `.github/workflows/deploy.yml` `changes` job, path filters, branch/event routing outputs, and deploy job `if:` blocks | Read this workflow as the authoritative deploy-routing contract; do not recreate routing policy in an unrelated config file. |
| Path filtering | `dorny/paths-filter` definitions in `.github/workflows/deploy.yml` | Parse the named filters and evaluate representative path sets against them; keep the test vocabulary aligned with `core`, `range`, `shifter_engine`, `shifter_platform`, `portal_image`, `quality_only`, and `gcp`. |
| Reusable deploy workflows | `.github/workflows/_core.yml`, `_range.yml`, `_shifter-engine.yml`, `_shifter-platform.yml`, `_gcp-dev.yml` | Inspect runner labels, `workflow_call` inputs, and plan/apply/deploy job gates without executing cloud steps. |
| Quality wiring | `.github/workflows/_quality.yml` existing lint/test job shapes | Add the suite as a normal Quality job with `contents: read`, no secrets, and no cloud permissions. |
| Existing architecture checks | `scripts/adr_guard/adr_guard.py`, `scripts/adr_guard/tests/test_adr_guard.py`, ADR-003-R2, ADR-003-R3, ADR-003-R4 | Build beside these checks rather than duplicating their exact narrow assertions; update ADR docs only when the new suite becomes a named architecture guardrail. |
| YAML dependency precedent | `_quality.yml` `uv run --python 3.11 --with 'pyyaml==6.0.2'` for ADR guard | Reuse the pinned PyYAML runner pattern unless the implementation creates a package-local `pyproject.toml` for the suite. |
| Workflow docs | `docs/adr/index.yaml`, `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md`, existing `docs/architecture/*preflight*.md` notes | Keep operator and ADR-enforcement docs in sync if the implementation changes guardrail semantics, not just test files. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- GitHub event/auth surface: the suite runs on the normal Quality path for PRs
  and direct validation. It must not request `id-token: write`,
  `pull-requests: write`, cloud secrets, environment approvals, or self-hosted
  runners.
- Runner exposure surface: tests must explicitly prove that `pull_request`
  events cannot reach any deploy job whose callee or local job uses
  `self-hosted`. Checking only the caller job's `if:` expression is not enough;
  reusable workflow `runs-on` labels are part of the exposure boundary.
- Secret-handling surface: workflows contain secret names and cloud resource
  identifiers. The suite may report file path, job id, guard id, event, branch,
  and boolean outputs, but must not print secret values, rendered tfvars,
  environment dumps, task-definition JSON, or credentials.
- Config-shape layer: PyYAML or an equivalent safe loader is the parser gate.
  The suite should fail on malformed or missing expected workflow keys rather
  than silently treating absent jobs, filters, `needs`, or `if:` blocks as
  "not applicable".
- Workflow-policy layer: `actionlint` remains the syntax policy gate, while the
  new suite evaluates semantic gating. Do not make actionlint success a proxy
  for branch/event/path correctness.
- OS/process exposure: keep all test inputs as fixture data and file paths. Do
  not pass secret-like workflow contents through shell argv, enable shell trace
  for parsed workflow bodies, or write generated artifacts outside the test
  workspace.
- Error and observability surface: failures should use ordinary test assertion
  output that includes the guarding issue/finding. GitHub Actions annotations
  are optional; a failing test with a clear case name is sufficient.

Maintainability incumbents the implementation must build on:

- `deploy.yml` as the one place that turns GitHub event, branch, and changed
  paths into deploy routing outputs.
- Existing named filters and job ids instead of new names that hide the current
  workflow contract.
- ADR guard for ADR-owned invariants, especially plan scope, saved plans,
  deploy fail-loud behavior, and portal deploy mode.
- Quality's existing Python execution pattern with pinned PyYAML, unless a
  small package-local test tool is justified by repeated reusable helpers.

Extensibility seam:

The suite needs a small data seam for scenarios: event name, ref/base branch,
changed paths, expected `changes` outputs, and expected reachable job modes
(`none`, `plan-only`, `plan+apply`, `deploy`). This is the right place to add a
future branch, provider, or deploy mode. Do not hardcode the current four branch
names into scattered assertions.

## Whole-Repo Scope

In scope for the implementation:

- `.github/workflows/deploy.yml`
- `.github/workflows/_quality.yml`
- `.github/workflows/_core.yml`
- `.github/workflows/_range.yml`
- `.github/workflows/_shifter-engine.yml`
- `.github/workflows/_shifter-platform.yml`
- `.github/workflows/_gcp-dev.yml`
- A repo-native Python test/check location, following existing Quality jobs and
  `scripts/*/tests` or `scripts/adr_guard/tests` patterns
- `docs/adr/index.yaml` and
  `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md`
  if the suite is promoted into an ADR-named guardrail
- `.gc/plan-rules.md` and `AGENTS.md` only if completion criteria or mandatory
  local checks change

Out of scope unless the tests expose an actual deploy contract bug:

- Terraform module redesign, runtime Django settings, AWS/GCP IAM trust,
  environment secrets, OIDC role configuration, ECR/SSM/ECS/GKE behavior,
  Guacamole runtime behavior, and provisioner business logic.

## Gotchas And Anti-Patterns

- Do not parse GitHub Actions booleans as Python truthiness. Workflow outputs
  are strings such as `'true'` and `'false'`, and `needs.<job>.result` has a
  finite result vocabulary.
- Do not treat `cancelled` differently from `failure` unless the issue
  explicitly calls for it. For upstream deploy dependencies, both must block
  downstream deploy jobs.
- Do not let the test suite pass by only checking that an `if:` block contains
  the word `success`. It must identify the relevant upstream dependency and
  require `success || skipped`.
- Do not collapse `shifter_platform` Terraform routing and `portal_image` app
  deploy routing. #913 deliberately split them.
- Do not make `workflow_dispatch` on every branch a production apply path.
  The protected prod-apply path is `workflow_dispatch` on `main`.
- Do not turn the branch/event matrix into a copy of current code comments.
  The tests should evaluate parsed workflow structure and representative path
  scenarios.
- Do not wire this into a deploy branch only. Acceptance requires Quality on
  every PR without cloud access.
- Do not weaken `deploy-workflow-plan-scope`,
  `deploy-verification-fail-loud`, `actionlint`, pre-commit, or PR Gate to make
  the new suite pass.

## Non-Goals

- No implementation in this preflight note.
- No new deploy framework, workflow DSL, exception hierarchy, schema registry,
  logging framework, cloud simulator, persistence model, or GitHub Actions
  execution harness.
- No cloud credentials, long-lived tokens, self-hosted runner usage, Terraform
  plan/apply, kubectl, AWS CLI, or GCP CLI calls in the suite.
- No attempt to replace actionlint, ADR guard, Terraform validation, or runtime
  deploy verification.
- No requirement or Ground Control traceability object is created for this
  requirement-free issue; #921 is the authoritative contract.

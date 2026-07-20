# Provisioner Deploy Test Gate Preflight (#555)

Status: pre-implementation guidance

Date: 2026-06-28

Issue: GitHub #555, "Architecture review: restore a blocking test gate for
provisioner deploys".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

The deployable engine provisioner image must not be built, pushed, or deployed
from a commit that has only passed a Docker-build validation. A blocking,
clearly named fast provisioner test gate must sit in the engine deploy path for
pull requests and deploy-triggering AWS branches. Slower or noisy coverage can
exist only as an explicit non-blocking supplement.

Keep these concepts separate:

1. Image buildability: `_shifter-engine.yml` currently validates that the
   Dockerfile can build locally.
2. Fast provisioner correctness: the blocking pytest suite that must gate PRs,
   image push, and ECS task-definition updates.
3. Whole-repo Quality: `_quality.yml` provides the broader path-routed lint,
   SAST, typecheck, tests, coverage, and Sonar surfaces.
4. Deploy routing: `deploy.yml` decides when AWS deploy branches call
   `_shifter-engine.yml`; reusable workflow internals should not recreate that
   router.
5. Cloud deployment verification: ECS/ECR/AWS OIDC steps remain deploy-runtime
   concerns, not test-suite setup.

## Architecture Decisions

- Reuse the existing provisioner project and test command shape. The canonical
  full provisioner test command is in `_quality.yml` under
  `shifter-engine-tests`: `uv sync --group dev` and
  `uv run --with pytest-cov pytest tests/ --cov=. --cov-report=xml:coverage.xml`
  from `shifter/engine/provisioner`.
- The engine reusable workflow must expose a blocking test job or equivalent
  blocking gate that runs on GitHub-hosted runners with `contents: read` only.
  The credentialed `build` and `deploy` jobs must depend on that gate.
- The current Docker-build validation can stay, but it is not the test gate.
  If kept, it should be a separate image-shape validation dependency or a step
  after tests; do not let its existence satisfy the acceptance criteria.
- The top-level Quality job is not sufficient by itself for deploy branches:
  deploy-branch pushes intentionally allow `needs.quality.result == 'skipped'`
  because the SHA is expected to have passed Quality on `dev`. The engine
  reusable workflow therefore needs its own deploy-path blocking test gate.
- If a slow/flaky provisioner suite is split out, the split must use pytest
  markers or an explicit job/input name that makes the blocking/non-blocking
  boundary visible. Do not hide runtime skips in commit messages, labels, or
  broad `continue-on-error`.
- Pin the new invariant in the existing workflow-as-data verification model
  (`scripts/adr_guard/tests/test_deploy_workflow.py`, backed by the `_dw_*`
  helpers in `scripts/adr_guard/adr_guard.py`). Syntax lint alone cannot prove
  that `build` and `deploy` depend on the right test gate.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #555 |
| --- | --- | --- |
| Provisioner tests | `_quality.yml` `shifter-engine-tests`; `shifter/engine/provisioner/pyproject.toml`; `pytest.ini` | Reuse the existing uv/pytest setup and markers; add only the minimum suite selection needed to make the fast gate explicit. |
| Engine image deploy | `_shifter-engine.yml` `validate`, `build`, and `deploy` jobs | Add the blocking test gate in this reusable workflow so build/push/deploy cannot run on an untested commit. |
| Deploy routing | `deploy.yml` `changes` output `shifter_engine`, branch/event matrix, and `shifter-engine` reusable-workflow call | Keep routing centralized here; do not add a second branch router inside the reusable workflow. |
| Workflow semantic checks | `scripts/adr_guard/adr_guard.py` `_dw_*` helpers and `scripts/adr_guard/tests/test_deploy_workflow.py` | Extend the model/tests to assert engine build/deploy depend on the provisioner test gate. |
| Architecture docs | `docs/adr/index.yaml` ADR-003, `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md` | If the implementation promotes this to a named ADR guardrail, update ADR docs in the same change. |
| Release-note trail | `changelog.d/README.md` | CI/CD behavior changes need a `changed` or `fixed` fragment. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- GitHub auth surface: test jobs run on `ubuntu-latest`, with
  `permissions: contents: read`; no `id-token: write`, cloud secrets, GitHub
  Environment binding, or self-hosted runner use.
- Deploy credential surface: only the existing `build` and `deploy` jobs assume
  AWS via `aws-actions/configure-aws-credentials`; their `needs` graph must make
  a successful blocking test gate a prerequisite.
- Secret-handling surface: tests must not require AWS/GCP secrets, rendered
  tfvars, task-definition JSON, or live credentials. Failure output should name
  paths, job ids, and test names, not secret values or environment dumps.
- Config-shape layer: workflow semantic checks should parse YAML through the
  existing `_dw_*` model and fail closed on missing jobs, missing `needs`, or
  malformed workflow shapes. Do not use comment-aware string greps as the only
  guard.
- OS/process exposure: do not pass secret-bearing workflow bodies or environment
  values through shell argv or `set -x`. The provisioner test command should use
  local files and test fixtures only.
- Error and observability surface: GitHub Actions failures should fail loudly
  through normal test/job failure. Optional advisory suites must be visibly
  named non-blocking and must not mask the blocking gate.

Maintainability incumbents the implementation must build on:

- `_quality.yml`'s existing provisioner uv/pytest setup and `provisioner`
  path category.
- `_shifter-engine.yml`'s existing hosted `validate` job and credentialed
  self-hosted `build` / `deploy` split.
- `deploy.yml` as the only branch/event/path router.
- `scripts/adr_guard/tests/test_deploy_workflow.py` for reusable workflow
  topology and dependency invariants.
- ADR-003 / ADR-004 enforcement, `actionlint`, and the repo-required
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`.

Extensibility seam:

The suite boundary should be parameterized as a named fast provisioner gate
(`fast`, `not slow`, or an equivalent explicit marker/job name) with an
optional advisory slow suite. Future provider-specific provisioner coverage
should extend that marker/job boundary, not require rewriting the deploy router
or credentialed build/deploy jobs.

## Whole-Repo Scope

In scope for implementation:

- `.github/workflows/_shifter-engine.yml`
- `.github/workflows/deploy.yml` only if the reusable workflow inputs/outputs
  must change
- `.github/workflows/_quality.yml` only if the canonical provisioner test
  command or suite split changes
- `shifter/engine/provisioner/pytest.ini` and test markers only if the fast/slow
  split is made explicit
- `scripts/adr_guard/tests/test_deploy_workflow.py` and possibly
  `scripts/adr_guard/adr_guard.py` if helper support is needed
- `docs/adr/index.yaml` and ADR enforcement docs if a new hard guardrail is
  added
- `changelog.d/555.fixed.md` or `changelog.d/555.changed.md`

Out of scope unless a test gate exposes an actual product bug:

- Provisioner business logic changes
- Terraform module redesign
- AWS IAM role/trust changes
- ECR immutability or ECS task-definition image identity changes
- Portal, range, GCP, Kubernetes, Guacamole, or worker deploy redesign

## Gotchas And Anti-Patterns

- Do not satisfy the issue with `docker build` alone. Buildability is not
  behavioral test coverage.
- Do not rely only on the top-level Quality job for deploy branches; it is
  intentionally skippable on deployment branches.
- Do not add cloud-backed tests to the blocking fast gate.
- Do not put the test gate on `self-hosted` or give it AWS/GCP/OIDC
  permissions.
- Do not use `continue-on-error`, `|| true`, broad `if: always()`, or
  `needs.<job>.result != 'cancelled'` shapes on the blocking gate.
- Do not comment out a slow suite. Mark it, name it, and wire it explicitly as
  blocking or advisory.
- Do not duplicate branch/path routing in `_shifter-engine.yml`; that belongs
  in `deploy.yml`.
- Do not weaken `actionlint`, ADR guard, PR Gate, skip-tests policy, ECR digest
  pinning, or deploy fail-loud behavior to make the new gate pass.

## Non-Goals

- No implementation in this preflight note.
- No new CI framework, workflow DSL, exception hierarchy, schema registry,
  provisioner abstraction, cloud simulator, or persistence model.
- No live AWS/GCP calls, Terraform plan/apply, ECS mutation, ECR push, or
  self-hosted runner access from the test gate.
- No requirement or Ground Control traceability object is created for this
  requirement-free issue; #555 is the authoritative contract.

# Engine Validate Runner Acquisition Preflight (#1474)

Status: pre-implementation guidance

Date: 2026-07-13

Issue: GitHub #1474, "Engine 'Validate' deploy job flakes on GitHub-hosted
runner acquisition".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as deploy-control-plane reliability, not as an Engine provisioner
runtime feature. The failure mode is that `_shifter-engine.yml` `validate`
waited on `ubuntu-latest` runner acquisition with no steps started, then
cancelled, which caused the AWS Platform stage to be skipped by the existing
fail-closed dependency chain.

Keep these concepts separate:

1. Provisioner behavioral tests: the #555 blocking `test` gate remains a
   hosted, `contents: read` pytest job.
2. Engine image-shape validation: the local `docker build --no-cache` gate in
   `_shifter-engine.yml` validates Dockerfile/build context before image push.
3. Credentialed image build and ECS deploy: the existing self-hosted `build`
   and `deploy` jobs assume AWS roles, push ECR images, attest provenance, and
   update the ECS task definition.
4. Platform dependency gating: `_shifter-platform.yml` must not run on top of a
   failed or cancelled Engine deploy when the Engine path was selected.
5. Runner fleet health: EC2 self-hosted runner provisioning, network isolation,
   and health alerts live under the existing runner infrastructure docs and
   Terraform root.

Do not compensate for a runner-acquisition flake by making Platform ignore a
failed or cancelled Engine dependency.

## Architecture Decisions

- GitHub Actions has no native fallback order from `ubuntu-latest` to
  `self-hosted`; a workflow job chooses one concrete scheduling target.
  Step-level retries and shell timeouts cannot repair a job that never acquired
  a runner.
- The preferred direction is to make the trusted deploy-path Engine
  image-shape validation use the same self-hosted runner class as the
  credentialed Engine build/deploy path, with an explicit
  `github.event_name != 'pull_request'` guard if the job itself becomes
  self-hosted. The top-level caller already denies pull-request events, but the
  reusable workflow must remain safe if a future caller is added.
- Preserve the #555 test-gate contract. Do not move the `test` job to
  self-hosted or give it cloud/OIDC permissions as part of this issue unless
  #555 and the workflow-as-data tests are deliberately revised.
- Keep deploy routing centralized in `deploy.yml`. `_shifter-engine.yml`
  should own its internal validation/build/deploy dependencies, not re-create
  branch or path routing.
- A moved or hardened `validate` job still needs a generous `timeout-minutes`
  backstop, matching the #1220 convention for self-hosted jobs. Timeout is
  defense in depth; it does not replace runner health or capacity fixes.
- If the implementation chooses a hosted-runner hardening path instead, it must
  prove it handles acquisition-time cancellation, not only failures after steps
  start. A retry action around `docker build` is insufficient for this incident
  class.
- If the intended invariant changes, pin it in the existing workflow-as-data
  verification model in `scripts/adr_guard/tests/test_deploy_workflow.py` and,
  if promoted to an ADR check, `scripts/adr_guard/adr_guard.py` plus
  `docs/adr/index.yaml`.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1474 |
| --- | --- | --- |
| Deploy orchestration | `.github/workflows/deploy.yml` `changes` outputs, `shifter-engine` caller, and `shifter_platform` fail-closed `needs` gate | Do not add alternate branch/path routing or let Platform proceed after an Engine failure/cancellation. |
| Engine reusable workflow | `.github/workflows/_shifter-engine.yml` `test`, `validate`, `build`, and `deploy` jobs | Keep the image-shape gate in the existing workflow and preserve the test -> validate/build/deploy dependency. |
| Provisioner test gate | `docs/architecture/provisioner-deploy-test-gate-preflight-555.md`; `scripts/adr_guard/tests/test_deploy_workflow.py::TestProvisionerDeployTestGate` | Keep the blocking pytest job hosted, low-permission, and required by validate/build/deploy. |
| Runner exposure guard | ADR-003-R5 in `docs/adr/index.yaml`; `scripts/adr_guard/adr_guard.py` `deploy-workflow-runner-exposure` | Any self-hosted job in a reusable deploy workflow must be unreachable from `pull_request`. |
| Workflow semantic tests | `scripts/adr_guard/adr_guard.py` `_dw_*` helpers and `scripts/adr_guard/tests/test_deploy_workflow.py` | Extend parsed-workflow assertions instead of checking YAML comments or string fragments. |
| Runner scheduling policy | `docs/technical/platform_infrastructure/github-runners.md` | Keep the distinction between portable hosted quality jobs and trusted self-hosted deploy/image jobs. |
| Runner fleet | `platform/terraform/global/github-runner/**`, `docs/dev/aws-runner-provisioning-runbook.md`, `docs/ops/github-runner-health-alerts.md` | Use existing runner count, network-isolation, provisioning, and health-alert mechanisms before inventing another runner pool. |
| Workflow validation | `actionlint`, ADR guard, `_quality.yml` workflow-lint and adr-conformance jobs | Workflow edits must pass the existing syntax and architecture gates. |
| Change notes | `changelog.d/README.md` | CI/CD behavior changes need a small fixed/changed fragment. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- GitHub event/auth surface: no pull-request event may reach a self-hosted
  deploy-runner job. If `validate` becomes self-hosted, add a job-level guard
  the existing `deploy-workflow-runner-exposure` check can evaluate.
- Workflow permission surface: `validate` should keep `contents: read` only and
  must not request `id-token: write`, `attestations: write`, cloud secrets, or a
  GitHub Environment unless it becomes mutating.
- Cloud credential surface: only the existing `build` and `deploy` jobs should
  assume AWS roles, push ECR images, verify attestations, or register ECS task
  definitions. Local Docker validation must not receive deploy credentials.
- Secret-handling surface: no rendered tfvars, AWS/GCP credentials, GitHub
  registration tokens, task-definition JSON, or environment dumps should be
  logged, uploaded, passed as build args, or printed for this fix.
- Supply-chain action surface: any new third-party action in a workflow that is
  self-hosted or otherwise cloud-credentialed must be pinned to a full commit
  SHA under ADR-037-R1. Prefer no new action for runner retry/fallback.
- OS/runtime exposure: self-hosted Docker builds run against a persistent Docker
  daemon. Keep `--no-cache`, avoid privileged build flags and host bind mounts,
  and do not route untrusted PR Dockerfiles to that runner class.
- Config-shape layer: update the workflow-as-data tests when the expected
  runner class or job dependency changes. The model should fail closed on
  missing jobs, missing `needs`, or malformed `if` expressions.
- Error and observability surface: a real validation failure should fail the
  Engine workflow loudly. A runner-capacity issue should be diagnosed through
  the existing runner health/runbook path, not hidden behind `continue-on-error`
  or broad warnings.

Maintainability incumbents the implementation must build on:

- `_shifter-engine.yml` as the single owner of Engine image validation, image
  push, provenance attestation, and ECS task-definition update.
- `deploy.yml` as the only event/branch/path router.
- `scripts/adr_guard/tests/test_deploy_workflow.py` as the semantic workflow
  contract test surface.
- `docs/technical/platform_infrastructure/github-runners.md` and runner ops
  docs for runner scheduling and health assumptions.
- The existing #1220 timeout convention for self-hosted jobs.

Extensibility seam:

Represent runner placement policy as parsed workflow structure, not prose:
job id, expected runner class, expected PR reachability, permissions, and
required `needs`. That gives the next variation, such as a dedicated
`self-hosted,docker` label or a separate hosted PR image validation job, one
test-data surface to update. Avoid a free-form dynamic `runs-on` input unless a
second real caller appears and the allowed values are constrained by tests.

## Whole-Repo Scope

Likely in scope for the eventual implementation:

- `.github/workflows/_shifter-engine.yml`
- `scripts/adr_guard/tests/test_deploy_workflow.py`
- `scripts/adr_guard/adr_guard.py` only if the invariant becomes a named ADR
  guard rather than a test-suite assertion
- `docs/adr/index.yaml` and `docs/technical/dev/adr-enforcement.md` if a new
  ADR-enforced rule is added
- `docs/technical/dev/ci-cd.md` and
  `docs/technical/platform_infrastructure/github-runners.md` if runner policy
  wording changes
- `changelog.d/1474.fixed.md` or `1474.changed.md`

Conditionally in scope if root cause points at runner fleet capacity or health:

- `platform/terraform/global/github-runner/**`
- `docs/dev/aws-runner-provisioning-runbook.md`
- `docs/ops/github-runner-health-alerts.md`

Out of scope unless separate evidence requires it:

- Provisioner business logic, tests, or Dockerfile contents.
- Platform dependency gating that currently blocks on failed/cancelled Engine.
- AWS IAM trust, ECR immutability, attestation verification, ECS task-definition
  image identity, Terraform modules, Portal, Guacamole, GCP, Kubernetes, or
  runner bootstrap automation.

## Gotchas And Anti-Patterns

- Do not make Platform treat a cancelled or failed Engine workflow as skipped
  when the Engine path was selected. That would hide the failure and could
  deploy against a stale or missing Engine image digest.
- Do not add `continue-on-error`, `|| true`, `needs.<job>.result != 'cancelled'`,
  or a broad `always()` bypass around Engine validation.
- Do not satisfy this with a retry wrapper around `docker build` unless the
  acquisition-time cancellation class is independently handled.
- Do not route pull-request Docker builds onto self-hosted runners. If PR image
  validation is needed later, keep it hosted or add a separate trusted design.
- Do not move the #555 hosted pytest gate to self-hosted just because
  `validate` moves.
- Do not add another workflow, runner pool, schema, exception hierarchy,
  logging framework, or deploy router for one scheduling decision.
- Do not weaken `deploy-workflow-runner-exposure`, upstream fail-closed gating,
  action SHA pinning, actionlint, ADR guard, or runner-network guardrails.
- Do not log full workflow environments, Docker build args, task definitions,
  rendered tfvars, registration tokens, or cloud credential material while
  diagnosing the flake.

## Non-Goals

- No implementation in this preflight note.
- No change to product runtime behavior, provisioner orchestration, Terraform
  state, cloud IAM, ECR repositories, ECS services, or Platform deploy
  semantics.
- No attempt to build a GitHub Actions scheduler fallback mechanism; GitHub
  Actions does not provide runner-class fallback for a single job.
- No autoscaling runner fleet, new GitHub App, long-lived GitHub credential, or
  replacement runner health system.
- No Ground Control requirement or traceability object is created for this
  requirement-free issue.

## Validation

For this preflight documentation change:

```sh
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/engine-validate-runner-acquisition-preflight-1474.md --level fast
```

For the eventual workflow implementation, also run:

```sh
python3 scripts/adr_guard/adr_guard.py --all --level ci
actionlint
```

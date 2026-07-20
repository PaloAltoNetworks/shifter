# Deploy Fail-Loud Preflight (#914)

Status: pre-implementation guidance

Date: 2026-06-10

Issue: GitHub #914, "deploy: workflow deploy steps fail loud (guacd
stabilization + engine task family)".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Boundary

Treat both defects as deploy verification failures, not application runtime
features. The implementation should stay in the GitHub Actions deploy layer and
the existing AWS Terraform contracts that create the resources being verified.

- Guacamole ECS stabilization belongs in `.github/workflows/_shifter-platform.yml`
  after the portal Terraform apply because the Guacamole ECS services are
  Terraform-managed by `platform/terraform/modules/guacamole`.
- Engine task-definition image swapping belongs in
  `.github/workflows/_shifter-engine.yml`; the task definition family itself is
  Terraform-managed by `platform/terraform/modules/engine-provisioner` and
  exposed through the portal environment outputs/SSM wiring.
- The main orchestration and any declared bootstrap exception belong in
  `.github/workflows/deploy.yml`, matching the existing
  `gcp_require_active_certificate` pattern: automatic deploys fail closed, and a
  bootstrap bypass is explicit manual intent.
- Do not move these checks into Django, the provisioner container, Terraform
  modules, or ad hoc local scripts. The failure must appear on the deploy run
  that claimed to verify the deploy.

## Decisions

- A timed-out Guacamole stabilization wait is a failed deploy unless the
  workflow has an explicit, documented bootstrap exception. Increasing the
  timeout is acceptable if first boot needs it; converting timeout to warning is
  not.
- A missing engine ECS task definition family is a failed deploy after the
  platform stack has been applied. The only acceptable skip is an explicit
  first-deploy/bootstrap mode that the caller opts into and that still emits a
  clear warning.
- Bootstrap exceptions must be typed workflow inputs, not inferred from missing
  cloud resources, shell errors, branch names, or broad `workflow_dispatch`
  status.
- Verification diagnostics should name the environment, ECS cluster/service or
  task family, observed rollout states, attempt count, and timeout. They should
  not print secrets, rendered tfvars payloads, task-definition secret values, or
  credential-bearing URLs.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #914 |
| --- | --- | --- |
| Deploy orchestration | `.github/workflows/deploy.yml` job dependency chain and typed `workflow_dispatch` inputs | Add any AWS first-deploy exception at the orchestrator and pass it into reusable workflows explicitly. |
| AWS engine deploy | `.github/workflows/_shifter-engine.yml` `workflow_call` inputs, ECR login/build, `aws ecs describe-task-definition`, `jq` task-definition rewrite | Keep image swapping in the existing deploy job; fail the existing step instead of adding a parallel deploy path. |
| Engine task family source of truth | `platform/terraform/modules/engine-provisioner/task_definition.tf`, environment `module.engine_provisioner`, and portal outputs/SSM parameters | Do not duplicate family-name derivation outside the current environment naming contract except for the existing workflow env value. |
| AWS platform deploy | `.github/workflows/_shifter-platform.yml` apply job and Guacamole stabilization loop | Make the existing wait loop fail loud; preserve the circuit-breaker failed-state branch. |
| Guacamole infrastructure | `platform/terraform/modules/guacamole/**` ECS services, task definitions, service discovery, and deployment circuit breaker | Do not compensate for a bad image by weakening ECS deployment health or network/security groups. |
| Bootstrap precedent | `.github/workflows/deploy.yml` `gcp_require_active_certificate` and `_gcp-dev.yml` `require_active_certificate` | Use explicit manual bootstrap intent for rare first-deploy bypasses; automatic deploys remain strict. |
| Architecture enforcement | ADR-002, ADR-003, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `actionlint` | Workflow edits are guardrail-file edits and must include matching ADR/enforcement docs plus `actionlint` and ADR guard validation. |
| Operator docs | `shifter/shifter_platform/documentation/docs/technical/dev/ci-cd.md` and `docs/dev/deploy-secrets.md` | If a new bootstrap input or deploy behavior is operator-visible, document when it may be used and how to clear it. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- GitHub auth/OIDC surface: keep AWS credentialing through
  `aws-actions/configure-aws-credentials` with the existing `id-token: write`
  permissions. Do not introduce long-lived AWS secrets, PATs, or broader
  workflow permissions for a status check.
- Secret-handling surface: task definitions contain Secrets Manager references
  and deploy workflows render secret tfvars elsewhere. This issue should inspect
  ECS rollout status and task-family existence only; do not log task-definition
  JSON wholesale, rendered tfvars, secret ARNs when avoidable, Guacamole URLs,
  or container secret values.
- Env-binding and config shape: reuse typed `workflow_call` inputs and
  `workflow_dispatch` inputs. A bootstrap bypass should be a boolean with a
  precise name and default strict value. Avoid untyped magic env vars and avoid
  deriving behavior from branch names beyond the existing `deploy.yml`
  environment routing.
- AWS runtime validators: `aws ecs describe-services` rollout states and
  `aws ecs describe-task-definition` are the deployment truth sources. Continue
  treating `FAILED` rollout state as an immediate error, and treat timeout or
  missing expected task family as an error outside explicit bootstrap mode.
- OS/process exposure: service names, cluster names, family names, attempt
  counts, and rollout states are safe in command argv/logs. Do not place
  rendered local.auto.tfvars content, AWS credentials, Guacamole JSON auth
  secrets, RDP credentials, or signed URLs in command arguments or shell traces.
- Error envelope and observability: use GitHub Actions annotations
  (`::error::` for failed deploy verification, `::warning::` only for explicit
  bootstrap bypass). Logs should be enough to diagnose which verifier failed
  without creating a second monitoring or logging abstraction.

Maintainability incumbents the implementation must build on:

- `_shifter-platform.yml` existing Guacamole wait loop, attempt counter, ECS
  rollout-state queries, and circuit-breaker branch.
- `_shifter-engine.yml` existing task-definition fetch and register-revision
  flow.
- `deploy.yml` typed input propagation and dependency chain.
- `platform/terraform/modules/engine-provisioner` and
  `platform/terraform/modules/guacamole` as the source of managed ECS resource
  existence and names.
- ADR/actionlint validation rather than a new custom workflow framework.

Extensibility seam:

The required parameter seam is an explicit AWS bootstrap intent such as
`aws_first_deploy` or `allow_missing_engine_task_family`, defaulting to strict
failure and only available from deliberate manual dispatch. Keep timeout values
for deploy verifiers centralized near the existing wait loops so a future
environment-specific first-boot timeout can be changed without editing every
status check. Do not create a generic "ignore deploy verification failures"
flag.

## Whole-Repo Scope

In scope for the implementation:

- `.github/workflows/deploy.yml`
- `.github/workflows/_shifter-engine.yml`
- `.github/workflows/_shifter-platform.yml`
- `shifter/shifter_platform/documentation/docs/technical/dev/ci-cd.md` if
  operator-visible input or behavior changes
- `docs/adr/**` or
  `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md`
  as required by ADR-002 for workflow guardrail edits
- Targeted workflow tests are limited to static validation (`actionlint`) and
  any existing repo-native workflow guard checks unless a shell helper is
  extracted.

Out of scope unless evidence proves the verifier is wrong:

- Terraform module redesign, ECS service topology, ALB/Ingress routing,
  Guacamole authentication, RDP credential handling, Django settings, worker
  runtime behavior, and provisioner business logic.

## Gotchas And Anti-Patterns

- Do not keep `exit 0` after a timeout or missing required AWS resource in
  normal deploy mode.
- Do not replace the Guacamole wait with a blind sleep. The deploy must observe
  ECS rollout state and fail on non-convergence.
- Do not collapse `FAILED`, `UNKNOWN`, timeout, missing cluster, and explicit
  bootstrap into one warning path. These states have different meanings.
- Do not make every `workflow_dispatch` a bootstrap deploy. Bootstrap must be an
  explicit input with a strict default.
- Do not duplicate ECS family naming in a new script or Terraform output parser
  unless the workflow already consumes that source. The current family contract
  is Terraform-managed and environment-prefixed.
- Do not weaken ECS deployment circuit breakers, health checks, Terraform
  validation, actionlint, ADR guard, or path filters to make the workflow green.
- Do not log full `aws ecs describe-task-definition` output; it can carry
  secret references, environment details, and operational configuration beyond
  what this verifier needs.

## Non-Goals

- No implementation in this preflight note.
- No new deploy framework, exception hierarchy, schema layer, monitoring stack,
  or persistence model.
- No change to cloud credentials, IAM trust, GitHub token permissions, ECR
  repositories, Terraform state, ECS service definitions, Guacamole runtime
  configuration, or task-definition container fields beyond the verifier
  behavior needed by #914.
- No attempt to solve unrelated Guacamole first-click/user-session reliability;
  this issue is about CI/CD accurately failing when deploy verification fails.

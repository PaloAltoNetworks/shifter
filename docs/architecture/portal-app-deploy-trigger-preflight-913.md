# Portal App Deploy Trigger Preflight (#913)

Status: pre-implementation guidance

Date: 2026-06-11

Issue: GitHub #913, "deploy: restore an application-code deploy trigger for
the portal".

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as AWS deploy-routing work, not a portal runtime feature. The defect
is that an AWS environment-branch push can change code that is baked into the
portal image while the deploy workflow reports success without building or
converging that image.

Keep these concepts separate:

1. Terraform platform changes: inputs that require the portal Terraform plan and
   apply path.
2. Portal image changes: source files copied into
   `shifter/shifter_platform/Dockerfile` from the `./shifter` Docker context.
3. Quality-only source changes: repository source that should run Quality but
   should not deploy the AWS portal.
4. Deployment intent: branch/event routing that decides whether an AWS deploy is
   allowed at all.

Do not put `shifter/**` back into the `shifter_platform` filter. That would
recreate the Terraform-plan spam #913 is trying to avoid.

## Architecture Decisions

- Preserve `shifter_platform` as the Terraform/platform-infrastructure signal.
  It should continue to cover portal/Guacamole Terraform, environment portal
  roots, and the reusable platform workflow itself.
- Introduce or repurpose a separate portal-image signal for build/deploy. It
  must not be confused with the broad `quality_relevant` validation classifier;
  deploy routing and Quality routing intentionally answer different questions.
- Split reusable workflow inputs by concern. `apply_changes` is deployment
  permission for environment branches/manual dispatch; it is not enough to tell
  `_shifter-platform.yml` whether Terraform should run or whether only the
  portal image should deploy.
- The portal image build and deploy path must still wait for failed upstream
  AWS jobs and must not run after a failed portal Terraform apply when Terraform
  changes are present. App-only deploys may pass through skipped plan/apply
  jobs, but not failed or cancelled ones.
- Workflow dispatch remains a deliberate full deploy path. Automatic pushes
  should be driven by explicit path signals, not broad "any Shifter source"
  matching.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #913 |
| --- | --- | --- |
| AWS branch/event routing | `.github/workflows/deploy.yml` `changes` job and `run_aws` / `apply_aws` outputs | Keep deploy permission centralized in the orchestrator. Do not add branch parsing inside reusable jobs. |
| Path filtering | `dorny/paths-filter` block in `.github/workflows/deploy.yml` | Add or refine named filters there; do not duplicate changed-file parsing in shell. |
| Terraform platform plan/apply | `.github/workflows/_shifter-platform.yml` `plan`, `push-guacamole-images`, and `apply` jobs | Keep Terraform plan/apply gated on Terraform-relevant changes or manual dispatch, not app-only changes. |
| Portal image build | `.github/workflows/_shifter-platform.yml` `build` job and `shifter/shifter_platform/Dockerfile` | Reuse the existing Buildx/ECR tag flow and short-SHA output. Do not create a parallel image publisher. |
| Portal convergence | `.github/workflows/_shifter-platform.yml` `deploy` job | Reuse the existing SSM single-instance path, ASG instance-refresh path, SSM `/image-tag` contract, and fail-loud deploy checks. |
| Image input surface | `shifter/shifter_platform/Dockerfile` and `shifter/.dockerignore` | The image copies `shifter_platform`, `cyberscript`, and `installation`; exclude local envs, caches, venvs, and node modules through the existing dockerignore. |
| Architecture guardrails | `scripts/adr_guard/adr_guard.py`, `scripts/adr_guard/tests/test_adr_guard.py`, `docs/adr/index.yaml`, `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md` | Existing ADR-003-R2 only protects plan scope and Quality routing; update it intentionally if the new deploy signal changes the contract. |
| Operator docs | `shifter/shifter_platform/documentation/docs/technical/dev/ci-cd.md`, `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/cicd.md` | Update stale path-filter docs after behavior changes; the platform-infrastructure doc currently still says `shifter_platform` includes `shifter/**`. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- GitHub auth/OIDC surface: keep AWS credentialing through
  `aws-actions/configure-aws-credentials` with the existing caller permissions
  (`contents: read`, `id-token: write`, `pull-requests: write` where plan
  comments require it). Do not introduce long-lived AWS keys, PATs, or broader
  token scopes for path routing.
- Secret-handling surface: app-only deploy still writes a non-secret SSM
  `/image-tag` value and may update optional bootstrap email SecureString
  parameters through the existing deploy job. Do not log rendered tfvars,
  SecureString values, Secrets Manager values, queue URLs, or container env
  dumps while adding diagnostics.
- Env-binding shape: use typed `workflow_call` boolean inputs for separate
  concerns, for example `platform_changes` and `portal_image_changes`. Avoid
  untyped magic env vars or shell-derived booleans with duplicated branch logic.
- Config and policy validators: workflow edits must pass `actionlint`; guardrail
  edits must update ADR docs and tests; architecture changes must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
- OS/process exposure: path booleans, image tags, repository names, instance
  ids, ASG names, and command ids are acceptable in logs. Do not put secret
  bodies or rendered tfvars content into argv, GitHub step summaries, SSM command
  diagnostics, or PR comments.
- Error and observability surface: keep GitHub Actions annotations and the
  existing SSM/ASG deploy failure handling. A green run must mean the selected
  deploy path actually built the image, updated `/image-tag`, and converged the
  single instance or ASG.

Maintainability incumbents the implementation must build on:

- `deploy.yml` as the single place that turns branch/event/path information into
  reusable workflow inputs.
- `_shifter-platform.yml` as the single AWS portal image build/deploy workflow.
- `shifter/shifter_platform/Dockerfile` as the source of truth for which source
  directories affect the portal image.
- ADR-003-R2 / `deploy-workflow-plan-scope` as the guardrail that prevents
  app-only changes from launching Terraform plans.
- ADR-003-R3 / `deploy-verification-fail-loud` as the guardrail that prevents a
  selected deploy path from silently doing nothing.

Extensibility seam:

The needed seam is a typed reusable-workflow input pair:

- `platform_changes`: run portal Terraform plan/apply and prerequisite
  Guacamole image publication when the platform infrastructure contract changed
  or the run is a deliberate full manual dispatch.
- `portal_image_changes`: build/push/deploy the portal image when files copied
  into the portal image changed or the run is a deliberate full manual dispatch.

This keeps the next reasonable variation, such as "dependency-only portal image
deploy" or "portal docs are image content", as a path-filter update rather than
a rewrite of job dependencies or Terraform gates.

## Whole-Repo Scope

In scope for the implementation:

- `.github/workflows/deploy.yml`
- `.github/workflows/_shifter-platform.yml`
- `scripts/adr_guard/adr_guard.py` and
  `scripts/adr_guard/tests/test_adr_guard.py` if ADR-003-R2 needs to recognize
  the new deploy signal
- `docs/adr/index.yaml` and
  `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md`
  if the guardrail contract changes
- `shifter/shifter_platform/documentation/docs/technical/dev/ci-cd.md` and
  `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/cicd.md`
  after workflow behavior changes

Usually out of scope:

- Terraform module redesign, ECR repository changes, IAM trust changes, SSM
  parameter naming changes, Django settings, entrypoint secret hydration,
  Guacamole runtime behavior, GCP deploy routing, and engine deploy behavior.

## Gotchas And Anti-Patterns

- Do not gate portal deploys directly on the broad `quality_relevant`
  classifier without deciding whether engine, packer, installation, cyberscript,
  and in-app docs changes should deploy the AWS portal.
- Do not make app-only changes run portal Terraform `plan` or `apply`. The fix
  is to split plan/apply from image build/deploy, not to undo the May path-filter
  split.
- Do not let app-only deploys bypass failed upstream jobs. Skipped upstream jobs
  are acceptable only when their path filter did not select them.
- Do not let a skipped `apply` block app-only deploys purely because `build`
  has `needs: apply`; use the existing `needs.<job>.result` pattern so skipped
  and successful are distinguished from failed/cancelled.
- Do not update `/image-tag` without building and pushing the same short-SHA
  tag first.
- Do not treat all docs as equivalent without a conscious decision. Top-level
  `docs/**` should not trigger a portal deploy; in-app documentation under
  `shifter/shifter_platform/documentation/**` is copied into the portal image,
  so excluding it means those docs will not deploy automatically.
- Do not weaken `deploy-workflow-plan-scope`, `deploy-verification-fail-loud`,
  `actionlint`, Terraform validation, or Quality routing to make the workflow
  pass.

## Non-Goals

- No implementation in this preflight note.
- No new deploy framework, workflow parser, exception hierarchy, schema registry,
  logging framework, monitoring stack, or persistence model.
- No change to portal runtime configuration, app validation, auth surfaces,
  secret stores, Terraform state, ECR repositories, SSM parameter names, or AWS
  IAM policies unless the implementation uncovers an existing permissions bug.
- No attempt to solve GCP fast-path behavior or engine deploy asymmetry; #913 is
  limited to restoring the AWS portal application-code deploy trigger.

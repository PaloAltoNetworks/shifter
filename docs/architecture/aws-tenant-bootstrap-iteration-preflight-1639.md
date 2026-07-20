# AWS Tenant Bootstrap And Iteration Preflight (#1639)

Status: pre-implementation guidance

Date: 2026-07-13

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1639>

This is a requirement-free preflight. The GitHub issue title and body are the
shipping contract. This note records repo-wide guardrails for improving first
AWS tenant standup and deploy iteration speed; it is not an implementation
plan.

## Scope Boundary

Issue #1639 is bootstrap and deployment-operator experience work for AWS
tenants:

- non-interactive first-run bootstrap;
- AWS CLI pager safety in local/bootstrap automation;
- fresh-account and dirty-account leftover reporting, with an explicitly gated
  sweep path;
- faster deploy iteration by refreshing only the components that actually need
  a portal ASG roll;
- investigation and hardening of ASG/ELB health behavior when instance refresh
  appears stuck on transient "insufficient data" health.

Keep these concepts separate:

1. Bootstrap account setup: state bucket, temporary bootstrap IAM role, GitHub
   OIDC role, and per-instance backend config.
2. Deploy prerequisite preflight: tools, secrets, overlays, and manual
   prerequisites that must be surfaced before mutation.
3. Dirty-account lifecycle: discovery and optional recovery of Terraform-owned
   leftovers when state is missing or an earlier teardown was incomplete.
4. Portal application deploy: image digest rollout, SSM deploy body, ASG
   instance refresh, target-group health, and worker verification.
5. Engine provisioner deploy: ECS task definition image digest, not a portal
   EC2 image refresh unless a portal-consumed contract changed.

Do not turn this issue into a new deployment framework, provider abstraction,
Terraform resource registry, Django API, persistence model, exception
hierarchy, or application range cleanup workflow.

## Architecture Decisions

- Extend the existing `scripts/bootstrap` package. `deploy.py` remains the
  compatibility facade and executable entrypoint; new behavior belongs in
  focused modules called from `cli.py`, `preflight.py`, `aws_bootstrap.py`,
  `terraform_deploy.py`, or a similarly narrow bootstrap lifecycle module.
- Non-interactive bootstrap must be an explicit CLI mode, for example `--yes`
  or a clearly named CI/noninteractive flag. A non-TTY alone may skip prompts
  for preflight, but it must not silently authorize destructive sweep actions.
- AWS CLI pager suppression is a command-execution hygiene rule. Set
  `AWS_PAGER=""` in the bootstrap subprocess boundary and/or append
  `--no-cli-pager` for AWS CLI commands through the shared runner. Do not rely
  on every caller remembering an environment variable.
- Fresh-account leftover detection extends the shared preflight/reporting
  surface. Discovery is read-only by default. Mutation requires an explicit
  sweep/recovery action, account id, region, environment, summary of resources,
  and confirmation or a separate headless opt-in.
- Dirty-account recovery must reuse the #1472 ownership model: exact
  environment/resource names derived from Terraform inputs plus account,
  region, dependency context, and tags where available. A same-name resource is
  not ownership proof.
- ASG refresh decisions belong behind the existing topology/helper seam, not in
  ad hoc workflow shell. Use `scripts/portal_deploy/portal_deploy.py` for
  nontrivial refresh selection, waiting, status interpretation, and health
  diagnostics; keep `_shifter-platform.yml` as a thin caller.
- Terraform continues to own ASG/health-check configuration. If the health
  grace, health-check type, target-group readiness, warmup, or refresh
  preferences change, expose them as typed Terraform variables with validation
  and environment tfvars, not workflow literals.
- Engine-only image changes must not force a portal ASG refresh unless the
  portal host image, user_data, SSM runtime contract, or portal container image
  changed. Preserve the existing path-filter split between
  `shifter_engine`, `shifter_platform`, and `portal_image`.

No new ADR is required unless the implementation changes guardrails,
environment protections, Terraform ownership, deploy concurrency, destructive CI
authorization, or the repository's validation rules.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1639 |
| --- | --- | --- |
| Bootstrap CLI contract | `scripts/bootstrap/cli.py`, `deploy.py`, `BootstrapConfig`, `AWS_ENVIRONMENTS` | Add flags and commands through the existing parser and facade. Preserve `bootstrap`, `terraform`, `full`, `preflight`, and `runners` behavior. |
| Prompt/headless behavior | `bootstrap_core.confirm`, `confirm_or_manual`, `wait_for_user`, `preflight._resolve_headless` | Centralize noninteractive semantics. Do not add one-off `input()` checks or TTY probes in new code. |
| Subprocess and log safety | `bootstrap_core._validate_argv`, `_redact_argv_for_log`, `run_cmd`, `run_cmd_secret_stdin` | All external commands stay argv-list based, redacted, dry-run aware, and pager-safe. No `shell=True` or secret-bearing argv. |
| AWS bootstrap | `scripts/bootstrap/aws_bootstrap.py` | Reuse state bucket, temporary role, OIDC role, EBS encryption, dry-run, and cleanup conventions. Do not duplicate IAM bootstrap logic. |
| Shared deploy preflight | `scripts/bootstrap/preflight.py` and workflow invocations in `_core.yml`, `_range.yml`, `_shifter-platform.yml` | Add leftover discovery/reporting here or behind it so local and CI see the same readiness model. |
| Dirty-account lifecycle | `docs/architecture/aws-dirty-account-lifecycle-preflight-1472.md`, `docs/dev/aws-teardown-runbook.md` | Reuse discovery-by-exact-ownership, dry-run first, gated mutation, bounded retries, and no data-bearing auto-delete. |
| Terraform stack ownership | `platform/terraform/environments/{dev,proof,prod}`, `docs/dev/aws-terraform-apply-order.md` | Keep Core, Range, Engine image, Portal order and state keys. Do not create a second resource schema in Python. |
| Known leftover resources | `modules/ecr`, `modules/range/vpc/firewall.tf`, Portal `main.tf`, `modules/portal/rds`, `modules/guacamole/rds`, `modules/portal/backup-alerts`, `modules/portal/cognito/rotation.tf` | Map residue to existing Terraform resources: ECR repositories/KMS aliases, budgets, Network Firewall rule groups, RDS parameter groups, scheduler schedules, SNS/RDS event subscriptions. |
| Deploy path filters | `.github/workflows/deploy.yml` change detection and `_shifter-platform.yml` `platform_changes` / `portal_image_changes` inputs | Keep deploy routing single-sourced. Do not add a parallel branch-name or env-var trigger for refresh scope. |
| Portal topology and checks | `scripts/portal_deploy/portal_deploy.py` and `scripts/portal_deploy/tests/` | Put refresh-scope, wait, stuck-status, target-health, image, and worker checks in testable Python helpers. |
| ASG and ALB contracts | `platform/terraform/modules/portal/ec2`, `modules/portal/alb`, `modules/guacamole`, `docs/architecture/aws-long-lived-connection-drain-preflight-931.md` | Keep health, warmup, drain, target-group, and Docker stop timing explicit and ordered. |
| Validation and guardrails | `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard`, `.tflint.hcl`, `actionlint` | Docs-only preflight runs ADR guard. Implementation must run bootstrap tests plus tflint/actionlint for touched surfaces. |

No controller, DTO, repository, database migration, or application exception
incumbent applies. This issue should stay in operator CLI, workflow, Terraform,
and AWS API boundaries.

## Cross-Cutting Layers The Design Must Pass

- **Auth surface:** local bootstrap and sweep use the selected AWS CLI profile;
  CI deploy keeps GitHub OIDC and environment-protected roles. Before any sweep
  mutation, resolve STS caller identity and report account id, environment, and
  region. Do not add static AWS credentials or broaden deploy-role policies
  without a specific Terraform/IAM review.
- **Secret-handling surface:** tfvars payloads, GitHub secrets, SSM values,
  Secrets Manager values, runner tokens, database credentials, and generated
  backend files are sensitive. Leftover discovery may list names, ARNs, ids,
  tags, and states; it must not read or log SSM parameter values, secret values,
  rendered tfvars, service-account JSON, or command output that can contain
  credentials.
- **Env-binding shape:** preserve `AWS_PROFILE`, `TF_INFRA_STATE_BUCKET`,
  `SHIFTER_INSTANCE_DIR`, the `TF_VARS_<ENV>_*` secret names, and the deploy
  workflow's strict active-environment secret selection. Pager suppression
  belongs at the command-runner boundary as `AWS_PAGER=""`, not as a required
  operator shell setup.
- **Config validators:** keep Terraform variable validation as the authority
  for ASG health, warmup, drain, deregistration, and environment capacity
  values. Keep preflight's `Cloud`, `Mode`, `Status`, `CheckResult`, and
  `PreflightReport` shape for readiness output. Do not introduce duplicate
  HCL, tfvars, or Terraform-output parsers when existing helpers own the shape.
- **Ownership/policy gate:** sweep candidates must pass exact name/resource
  derivation and strongest available ownership evidence. KMS aliases, budgets,
  ECR repos, Network Firewall rule groups, RDS parameter groups, EventBridge
  Scheduler schedules, and SNS/RDS event subscriptions all have different
  tagging and async-delete behavior; ambiguous or conflicting evidence blocks
  mutation and reports the resource.
- **OS/process exposure:** every command is an argv list. Do not use shell
  strings, `set -x`, secret-bearing flags, or world-readable temp files. It is
  acceptable for non-secret resource names, ASG names, instance ids, target
  group ARNs, image digests, and timing values to appear in logs.
- **Error envelope and observability:** bootstrap uses `info/warn/error/success`
  and nonzero exits; `portal_deploy.py` uses `PortalDeployError`. Reports
  should include per-check/per-resource status such as `ok`, `warn`, `fail`,
  `absent`, `blocked`, `would-delete`, `deleted`, or `waiting`, plus concise
  AWS status reasons. Do not dump raw AWS responses by default.
- **Workflow surface:** deploy concurrency, branch/environment mapping,
  environment protections, and first-deploy manual opt-ins remain in
  `deploy.yml`. Workflow YAML should call reusable Python helpers for
  decisions and diagnostics rather than accumulating inline shell logic.
- **Terraform surface:** Core, Range, and Portal roots remain the source of
  resource contracts. Any health-grace or refresh-preference parameter belongs
  in the owning module and env tfvars, with tflint validation.

## Extensibility View

The necessary seam is a small AWS deploy-readiness and refresh-control surface:

- environment, region, account id, profile/role, and dry-run/mutate intent for
  bootstrap and leftover discovery;
- resource-specific leftover handlers that own exact identity, ownership proof,
  async wait behavior, and safe deletion/import refusal;
- portal refresh inputs that distinguish Terraform/platform changes, portal
  image changes, portal host/user_data changes, and engine task-definition-only
  changes;
- ASG timing parameters for health grace, instance warmup, min healthy percent,
  poll timeout, and stuck-health diagnostics.

The next reasonable variation should be addable by extending a handler or an
environment variable/tfvars value, not by editing every workflow branch. Examples
include another AWS environment, another leftover resource type, a shorter
proof/dev health grace, or a richer stuck-refresh diagnostic.

## Whole-Repo Surfaces In Scope

Likely implementation surfaces:

- `scripts/bootstrap/bootstrap_core.py`
- `scripts/bootstrap/cli.py`
- `scripts/bootstrap/preflight.py`
- `scripts/bootstrap/aws_bootstrap.py`
- a focused `scripts/bootstrap/*lifecycle*.py` or `*aws_preflight*.py` module
- `scripts/bootstrap/tests/`
- `.github/workflows/deploy.yml`
- `.github/workflows/_shifter-platform.yml`
- `scripts/portal_deploy/portal_deploy.py`
- `scripts/portal_deploy/tests/`
- `platform/terraform/modules/portal/ec2/**`
- `platform/terraform/modules/portal/alb/**`
- `platform/terraform/modules/guacamole/**`
- `platform/terraform/environments/{dev,proof,prod}/portal/**`
- `docs/dev/aws-teardown-runbook.md`, `docs/dev/aws-terraform-apply-order.md`,
  or `docs/dev/deploy-secrets.md` if operator behavior changes

Comparison and contract surfaces that should normally remain unchanged:

- `platform/terraform/modules/ecr/**`
- `platform/terraform/modules/range/vpc/**`
- `platform/terraform/modules/portal/rds/**`
- `platform/terraform/modules/guacamole/rds.tf`
- `platform/terraform/modules/portal/backup-alerts/**`
- `platform/terraform/modules/portal/cognito/rotation.tf`
- `scripts/terraform/render_aws_backend_configs.py`
- `scripts/bootstrap/terraform_backend.py`
- `docs/architecture/aws-dirty-account-lifecycle-preflight-1472.md`
- `docs/architecture/aws-long-lived-connection-drain-preflight-931.md`
- `docs/architecture/portal-app-deploy-trigger-preflight-913.md`

## Gotchas And Anti-Patterns

- Do not equate non-TTY with consent. `--yes` can approve ordinary bootstrap
  creation; destructive sweep needs its own explicit opt-in.
- Do not fix the AWS pager hang by requiring operators to export `AWS_PAGER`
  manually. Put it in the shared command boundary.
- Do not discover leftovers with broad substring matching such as "shifter" and
  delete the results. Prod/non-prod naming differs and a reused account may
  contain unrelated installations.
- Do not auto-delete data-bearing resources, KMS keys, buckets, snapshots,
  Secrets Manager secrets, databases, or SSM values outside exact
  non-value-reading prefixes. KMS aliases may be removable; KMS keys themselves
  require separate evidence and policy.
- Network Firewall rule group deletion is asynchronous and dependency-heavy.
  Treat "deleting" as a wait state with bounded polling, not as immediate
  absence.
- Do not auto-import same-name resources merely to make `terraform apply`
  proceed. Import transfers lifecycle authority and must require exact address
  mapping plus compatibility checks.
- Do not let an engine provisioner image-only deploy refresh the portal ASG.
  The engine provisioner is an ECS task consumed by the Portal stack, not a
  portal EC2 host replacement.
- Do not hardcode refresh preferences in workflow shell if Terraform already
  owns the timing contract.
- Do not treat EC2 instance health alone as proof that the portal target is
  ready. The "insufficient data" wedge must be diagnosed against ASG instance
  lifecycle, EC2 status checks, target-group health, lifecycle hooks, and warm
  pool state.
- Do not weaken WAF, `/admin` blocking, security groups, IMDSv2, KMS
  ViaService conditions, SSM prefix boundaries, deploy fail-loud behavior,
  actionlint, TFLint, ADR guard, or environment protections to speed iteration.

## Non-Goals

- No implementation in this preflight note.
- No formal Ground Control requirement, traceability link, application model,
  API, UI, Django service, repository, serializer, migration, or platform-wide
  logging change.
- No redesign of Terraform state layout, OIDC trust, IAM permissions boundary,
  runner registration, range/NGFW cleanup, provisioner runtime, CTF lifecycle,
  database schema, or GCP deploy behavior.
- No automatic recovery of arbitrary dirty accounts and no generic
  cloud-neutral cleanup framework.
- No production health-timing reduction without explicit environment-owned
  values and validation evidence.

## Validation Expectations For The Implementation

Run the bootstrap unit suite for CLI, preflight, confirmation, dry-run,
pagination, redaction, ownership, and sweep gates:

```bash
cd scripts/bootstrap && uv run ruff check . && uv run ruff format --check .
cd scripts/bootstrap && uv run pytest tests/ --cov=.
```

Run deploy helper tests when refresh logic moves into `portal_deploy.py`:

```bash
python3 -m unittest discover scripts/portal_deploy/tests
```

Run repository and stack-native gates for touched surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
```

Add Terraform fmt/validate for each touched root and live-account acceptance
evidence for the actual AWS behavior: noninteractive bootstrap, pager-safe AWS
commands, leftover report/sweep dry run, safe seeded-orphan handling, scoped
portal refresh skip on engine-only deploys, and refresh convergence through the
previous "insufficient data" condition.

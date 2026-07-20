# AWS Dirty-Account Lifecycle Preflight (#1472)

Status: pre-implementation guidance

Date: 2026-07-13

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1472>

> **Decision (2026-07-13).** #1472 ships as a runbook-only fix: an active
> post-destroy leftover sweep folded into `docs/dev/aws-teardown-runbook.md`,
> matching how #1431 / #1425 closed the earlier teardown gaps. The automated
> bootstrap-CLI recovery command described below (the extensibility seam and its
> safety constraints) is deferred to **#1618**, and complements #1287. The rest
> of this note stands as the design record for that follow-up.

## Scope Boundary

Issue #1472 is the shipping contract: an AWS environment that was previously
deployed and incompletely torn down must be deployable again without hand-run
AWS cleanup. The reported residue spans the Core and Portal Terraform roots:
Budgets, RDS parameter/subnet groups, ElastiCache subnet groups, EventBridge
Scheduler schedules, portal SSM parameters, the CTFd EC2 key pair, RDS event
subscriptions, and security groups.

This is environment-infrastructure lifecycle work. It is not application range
teardown, runtime reconciliation, or a reason to add Django schemas, services,
repositories, exceptions, or APIs. Issue #1431 owns the separate `global/iam`
bootstrap residue. Issue #1287 tracks turning the AWS teardown runbook into a
first-class destroy workflow; #1472 may build on that work, but must not create a
second teardown orchestration model.

## Architecture Decisions

- Terraform state remains the authoritative ownership and dependency graph.
  With usable state, fix and run the existing reverse-order destroy: Portal,
  Range, Core, followed by the separately owned runner and `global/iam` roots as
  documented in `docs/dev/aws-teardown-runbook.md`. Do not replace normal
  `terraform destroy` with a catalog of AWS CLI deletes.
- Dirty-account recovery is a narrow fallback for resources whose state is
  absent. It must be implemented through the existing `scripts/bootstrap` CLI
  support layer, not duplicated as workflow YAML or a standalone shell script.
  Local and CI entrypoints, if both are exposed, must call the same Python
  operation.
- Discovery is read-only by default. Mutation requires an explicit recovery or
  teardown action, the resolved AWS account id and region in the summary, the
  selected `dev|proof|prod` environment, and the existing interactive
  confirmation convention. A headless path must require an equally explicit
  opt-in; merely naming an environment is not destructive authorization.
- A same name is a lookup key, not ownership proof. An orphan may be mutated
  only when its identity is derived from the canonical Terraform naming and the
  strongest available ownership evidence agrees: account, region (or explicit
  global scope), environment, expected VPC/dependencies, and
  `Project=shifter`, matching `Environment`, and `ManagedBy=terraform` tags
  where the resource supports tags. Missing or conflicting evidence fails
  closed and reports names/IDs only.
- Prefer deletion and clean recreation for replaceable control-plane residue
  when state is gone. Adoption/import is allowed only for an explicitly mapped
  Terraform address after compatibility checks show that preserving the object
  is intentional and safe. Never auto-import a security group merely because
  its name matches: unmanaged rules and a wrong VPC turn adoption into a
  network-policy bypass. Never auto-delete or auto-adopt a live database,
  snapshot, secret value, KMS key, bucket contents, or other data-bearing
  resource under this issue.
- The Portal Parameter Store boundary is exactly
  `/shifter/<env>/portal/`. Terraform owns most names through
  `modules/portal/ssm`; `_shifter-platform.yml` also writes `image-digest` and
  the optional bootstrap-admin parameters and updates Terraform's `image-tag`.
  Teardown/recovery may enumerate and delete parameter *names* below that exact
  prefix without reading values. It must preserve `/shifter/ami/*` and every
  other environment's prefix.
- Recovery is convergent and retry-safe. “Absent” is success, dependency or
  eventual-consistency failures use bounded retries, and a partial run can be
  rerun. Dependency order must be explicit where AWS requires it: consumers
  before subnet/parameter groups and security groups; schedule before its role;
  RDS event subscription before its topic/key teardown; SSM prefix cleanup only
  after Portal workloads are stopped.
- No new ADR is required. These constraints apply the repository's existing
  Terraform ownership, environment binding, least-privilege, and bootstrap CLI
  decisions. A future implementation that creates a new general account
  adoption policy, weakens ownership evidence, or adds a destructive CI
  workflow is architecture work and must update the ADR registry in that
  change.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1472 |
| --- | --- | --- |
| Stack ownership/order | `platform/terraform/environments/{dev,proof,prod}`, their `portal` and `range` roots; `docs/dev/aws-terraform-apply-order.md`; `docs/dev/aws-teardown-runbook.md` | Preserve the existing root/state-key boundaries and reverse dependency order. Do not duplicate resource definitions in cleanup code. |
| CLI orchestration | `scripts/bootstrap/cli.py`, compatibility facade `deploy.py`, focused modules such as `terraform_deploy.py`, and `bootstrap_core.run_cmd` | Add one focused lifecycle operation behind the existing CLI conventions, dry-run/reporting, confirmations, subprocess redaction, and tests. Do not grow the facade with implementation logic. |
| Account/env identity | `BootstrapConfig`, `AWS_ENVIRONMENTS`, `get_aws_account_id()`, and `scripts/bootstrap/preflight.py` | Reuse `dev|proof|prod`, `us-east-2`, AWS profile handling, caller-identity lookup, and fail-safe prerequisite reporting. Do not add a second environment parser. |
| Backend/state mapping | `scripts/bootstrap/terraform_backend.py` and `scripts/terraform/render_aws_backend_configs.py` | Resolve the existing backend and stack keys; do not guess state locations or introduce another registry. |
| Ownership/naming | AWS provider `default_tags`, environment `terraform.tfvars`, module `common_tags`, and `docs/technical/dev/terraform.md` | Derive expected names from Terraform inputs and require tags/dependency context where supported. Keep prod's naming differences explicit. |
| Reported Core residue | `aws_budgets_budget.s3_cost_alert` in each environment Core root | Treat AWS Budgets as account/global-service scoped even though the provider runs in `us-east-2`; select the exact environment budget name, never all Shifter-looking budgets. |
| Reported Portal residue | `modules/portal/{rds,redis,cognito,ssm,ctfd,backup-alerts}`, `modules/guacamole/{rds,security}`, plus Portal VPC/EC2/ALB security groups | Terraform resources and their module inputs are the resource contract. Recovery code may map exceptional residue to these existing addresses but must not create parallel resource schemas. |
| Workflow-owned SSM names | `.github/workflows/_shifter-platform.yml` (`PS_PREFIX`, image digest/tag, optional bootstrap-admin parameters) | Include these exact non-Terraform writes in the Portal prefix cleanup; keep secret values out of discovery, logs, argv, and reports. |
| Deletion-protection/stalls | `docs/architecture/network-firewall-delete-protection-preflight-934.md` and the teardown runbook's protection, bucket, ENI, log-group, and ECR ordering | Converge protection off before destroy and preserve existing special ordering. Do not use state removal as the ordinary solution. |
| IaC validation | `platform/terraform/validation-inventory.yaml`, `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `_quality.yml`, `scripts/adr_guard` | Keep every root in the canonical inventory and all checks blocking. New exceptions still require an owner, rationale, and expiry in `docs/adr/exceptions.yaml`. |

No controller, DTO, persistence repository, or application exception incumbent is
applicable: this path ends at the operator CLI, Terraform, and AWS APIs.
Application range lifecycle services and provisioner Terraform are separate
ownership domains and must not be reused for environment teardown.

## Cross-Cutting Layers The Design Must Pass

- **Authentication/authorization:** local execution uses the selected AWS CLI
  profile; CI continues to use GitHub OIDC and the environment-specific deploy
  role. Before mutation, call STS and display the account id. Do not add static
  AWS credentials, broaden the deploy-role policy without evidence, or let a
  GitHub event implicitly authorize destruction. GitHub runner deregistration
  remains its separate token lifecycle from the teardown runbook.
- **Secret handling:** SSM recovery calls list names and delete by name; they do
  not call `GetParameter(s)` with decryption. Secrets Manager values, Terraform
  secret outputs/state, tfvars payloads, GitHub secrets, registration tokens,
  and database credentials must never enter reports. Reuse `run_cmd`'s logging
  and redaction conventions. Pass structured argv; do not interpolate secrets
  into shell strings or process argv. The environment prefix and AWS resource
  IDs are non-secret but should still be bounded in log volume.
- **Environment/config shape:** `AWS_ENVIRONMENTS`, `BootstrapConfig`, Terraform
  typed variables/validations, existing tfvars overlays, and
  `terraform_backend.py` remain canonical. Recovery accepts the same env,
  profile, region, bucket/backend, and dry-run/headless shapes; it does not add
  `shifter.yaml`, Django settings, SSM runtime configuration, or a generic
  `environment_mode` toggle.
- **Ownership/policy validation:** Terraform provider validation, tags, exact
  name derivation, VPC/dependency checks, and the resource-specific compatibility
  check all run before mutation. Security-group recovery verifies VPC plus tag
  ownership and refuses unexpected attachments/rules; it never weakens ingress
  or egress to make deletion succeed. SSM is constrained to the exact
  environment Portal prefix.
- **OS/process exposure:** use subprocess argument lists through the existing
  helper. Do not use `shell=True`, generated executable scripts, command strings
  containing credentials/config blobs, world-readable temp files, or local
  files under the repository for backend/tfvars material. Continue using the
  per-instance config directory outside the checkout and runner temp paths in
  CI.
- **Errors and observability:** operator failures use the existing
  `info/warn/error/success` CLI surface and non-zero exit behavior. Report a
  per-resource action (`kept`, `absent`, `would-delete`, `deleted`, `blocked`,
  `failed`) plus account/env/region and a final count; redact values and raw AWS
  response bodies. Terraform/provider failures remain Terraform failures. Do
  not introduce Django/API error envelopes or a parallel exception hierarchy.
- **Workflow and concurrency:** preserve deploy workflow concurrency and
  environment gates. A future destroy workflow must be manually dispatched,
  environment-protected, non-cancellable during Terraform mutation, and a thin
  caller of the same lifecycle code—not inline resource cleanup duplicated in
  YAML.

## Extensibility Seam

The required seam is the existing environment/stack boundary plus a small,
resource-specific recovery operation: environment, account id, region, and
dry-run/mutate intent are inputs; each exceptional resource handler owns its
identity, ownership proof, dependency check, and idempotent delete/import
behavior. Shared command execution and reporting belong in the bootstrap
support layer.

Do not create a second manifest that copies every Terraform resource. Add a
handler only for a provider resource class that demonstrably survives normal
destroy or for a non-Terraform write such as workflow-owned SSM parameters. The
next residue type should be addable without editing environment-specific
workflow YAML or cloning the whole orchestration path.

## Gotchas And Anti-Patterns

- `terraform destroy` does not update deletion-protection attributes first.
  Apply the owning root with protection disabled before destroy.
- Destroy success does not prove absence: AWS services can recreate log groups,
  Lambda ENIs can delay subnet/SG removal, and eventual consistency can make a
  just-deleted global name appear occupied. Verify absence with bounded polling.
- Terraform-managed SSM parameters and workflow-written parameters share one
  prefix. Cleaning only the module misses deployment parameters; recursively
  deleting `/shifter/*` destroys shared AMI references and other environments.
- `image-tag` is Terraform-owned but intentionally updated by the deploy
  workflow with `ignore_changes`. Do not “fix” that dual writer as part of this
  issue; teardown only needs to remove the parameter after workloads stop.
- Importing an object transfers lifecycle authority to Terraform. Never import
  without an exact resource address, compatibility check, and a post-import
  plan showing no unexpected security or data mutation.
- `terraform state rm` abandons an object and is not cleanup. Keep it limited to
  documented `prevent_destroy` exceptions that intentionally survive; do not
  use it to make the destroy command green.
- Do not discover by broad substring (`contains(name, "shifter")`) and delete
  the results. Prod/non-prod naming differs, some AWS resources are untaggable,
  and a previously used account may contain unrelated installations.
- Do not swallow AWS errors with `|| true`. Only an explicit not-found response
  is success; authorization, throttling exhaustion, dependency, and ownership
  failures remain blocking and visible.
- Do not place cleanup logic in `_shifter-platform.yml`, copy the same logic into
  all three environment roots, or add lifecycle behavior to Portal application
  services. These create duplicate workflow logic and concept confusion.

## Non-Goals And Implementation Boundaries

- No application range/NGFW cleanup, provisioner state reconciliation, CMS/CTF
  lifecycle behavior, database migration, model, serializer, API, or UI change.
- No global IAM/OIDC/boundary-policy fix from #1431, and no change to GitHub
  runner registration-token handling.
- No automatic deletion of databases, snapshots, secrets, KMS keys, buckets or
  bucket contents, AMIs, `/shifter/ami/*`, or resources belonging to another
  environment/account/VPC.
- No attempt to make arbitrary third-party or manually created same-name
  infrastructure adoptable. Ambiguous ownership is a blocker, not a heuristic.
- No generic cloud-neutral lifecycle framework and no GCP behavior change.
- No weakening of deletion protection, network policy, Terraform checks,
  Checkov, TFLint, actionlint, ADR guard, environment protections, or deploy
  concurrency.

## Validation Expectations For The Implementation

Unit tests should exercise discovery/classification, exact prefix/name bounds,
ownership conflicts, dry-run, confirmation/headless gates, not-found
idempotency, pagination, bounded retry, partial failure, redaction, and
environment/account separation with injected command results—never live AWS.
Add a disposable-account acceptance sequence that proves create, destroy,
absence verification, recreate, plus a seeded verified-orphan recovery case.

Run the repository-required architecture and Terraform checks:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run the bootstrap unit suite, Terraform formatting and validation for each
affected root from `platform/terraform/validation-inventory.yaml`, and Checkov.
If workflow YAML changes, run `actionlint`.

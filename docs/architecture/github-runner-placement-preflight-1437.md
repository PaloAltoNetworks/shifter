# AWS runner placement preflight (#1437)

Date: 2026-09-12. Status: architecture decision; implementation and operational
migration remain outstanding. Repository inspected at `613f365ac`.

The supplied issue #1437 is the contract; no Ground Control requirement is
attached. This note records boundaries and evidence requirements, not an
implementation plan. It refines the placement guidance in the #1222 and #1433
preflights; ADR-004-R20 and ADR-053-R3 govern together.

## Decision and current evidence

Choose option 2: standardize reproducible isolated placement using the **existing**
`platform/terraform/global/github-runner` root and its
`modules/github-runner-network` module. The module already supplies a dedicated
VPC, private runner subnet, public NAT tier, and encrypted flow logs. Bootstrap
`deploy.py runners` already selects `create_runner_network=true`. A second root,
network implementation, or bootstrap orchestrator is unnecessary.

The issue background is partly historical: `dev.tfvars` still enables
`allow_default_vpc`, while `proof.tfvars` currently contains explicit placeholder
IDs, not that opt-in. The Terraform root defaults `create_runner_network=false`;
bootstrap overrides it, and `scripts/runner-deploy.sh` still uses the dev baseline.
Therefore the remaining contract is consistent supported defaults, safe lifecycle
handling, and demonstrated adoption, not merely the existence of a module.
No live tenant inventory was inspected; this note does not establish where
current runners actually live.

Retain `allow_default_vpc=false` as the fail-closed default. Default placement
is an explicit, documented exception, never the standard or an automatic fallback
from failed creation/discovery. New or renewed departures use the central ADR
exception registry with owner, scope, reason, and expiry. Do not grandfather
dev/proof silently. Preserve explicit `vpc_id` / `subnet_id` for an existing
compliant network; a portal private tier is only an optional existing dependency,
never a fresh-account prerequisite or a portal-owned runner lifecycle.

Range endpoints currently reference `aws_vpc.this.id` in `modules/range/vpc`.
That supports normal separation, but does not enforce that ranges can never
modify the runner network. A default-VPC risk acceptance cannot rest on that
source-code convention. AWS documents that endpoint private DNS installs a
VPC-scoped hidden hosted zone; network separation must also exclude shared
private-zone associations and Resolver forwarding that reintroduce the range
DNS scope. See [AWS PrivateLink DNS behavior](https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-access-aws-services.html).

Runner account ownership is a separate decision from VPC ownership. ADR-053-R3
forbids the development fleet in product/operator deploy-target accounts; its
maintainer-dev exception requires a re-creatable execution root and separate
state, with bootstrap runnable outside the tenant. This decision does not extend
that exception to arbitrary proof/prod/product accounts. Environment names alone
are not evidence of ownership. Preserve the existing runner state boundary;
platform teardown must not destroy it, while explicit full-account teardown can.

## Cross-cutting boundaries and incumbents

| Layer | Canonical incumbent and required behavior |
| --- | --- |
| Terraform ownership | `global/github-runner/{main,variables,outputs}.tf` owns hosts and selection; `modules/github-runner-network` owns networking. Preserve resource/state addresses. No copying portal, range firewall, or GCP network modules into a new runner stack. |
| Configuration and input shapes | `scripts/bootstrap/{cli,runner}.py`, `RunnerConfig`, `RunnerTarget`, and the existing Terraform variables are the contracts. Keep network configuration out of `.shifter.yaml`, application `shifter.yaml`, runtime env manifests, RAES contracts, Django settings, and API DTOs. `scripts/bootstrap/preflight.py` remains the deploy readiness owner; fresh runner creation must not acquire portal-secret prerequisites. |
| Selection and validation | Reuse Terraform types, variable validation, and the SG lifecycle preconditions for non-default placement and subnet membership. Treat managed creation, a complete explicit pair, and exceptional default discovery as distinct cases using the existing inputs. Preserve documented managed-network precedence; unused default discovery must not run in that mode. Missing, partial, contradictory, or unavailable inputs must have bounded, actionable failure rather than fallback or null/index errors. |
| AWS identity and authorization | Reuse bootstrap profile/region binding and `global/iam/github-oidc.tf`; validate the effective caller, intended account, region, and backend together before mutation. Setting `AWS_PROFILE` alone is not evidence that ambient credentials cannot override it. Keep operator provisioning, workflow OIDC, runner instance role, and runtime provisioner role distinct. No broad new host IAM grants to make a network move work. |
| Range exclusion | `modules/provisioner-iam` is the shared ECS/EKS permission owner, consumed by `modules/engine-provisioner/iam.tf` and EKS wiring. Its existing `range_vpc_id` seam and the `check_tf_iam_*` checkers are the incumbents. Prove effective denial of range endpoint/subnet/route mutations in the runner VPC; tags and a non-default VPC ID alone do not prove this. |
| Workflow trust | ADR-003, `deploy.yml`, its reusable workflows, `packer.yml`, and `scripts/adr_guard/_guard/checks/_deploy_workflow_runner_exposure.py` own trusted routing and timeout enforcement. Preserve hosted PR validation, protected environments, pinned actions, OIDC trust, and deployment gates. Generic `self-hosted` labels do not prove account isolation or that all eligible runners migrated. |
| Persistence and teardown | Reuse `scripts/bootstrap/terraform_backend.py`, `scripts/terraform/render_aws_backend_configs.py`, and `aws_env_destroy.py`. Keep encrypted S3 state and native locking, generated per-instance backend bindings, and explicit state ownership. Apply and destroy must resolve the same topology. No tracked live IDs, state copying, portal remote-state prerequisite, or second state registry. |
| Secret transport and OS | Keep credentials out of Terraform inputs, plans, state, user data, process argv, command-history payloads, and logs. Reuse `bootstrap_core._validate_argv`, redaction, and the `run_cmd_secret_stdin` contract where the transport supports it; argv validation does not validate an embedded remote shell. Retain SSM access, no inbound SSH, IMDSv2, the existing runner service, and health timer. |
| Errors and output parsing | Reuse `bootstrap_core` status/error helpers, runner output-to-target mapping, SSM terminal-status checks, and GitHub online verification. Terraform outputs must have usable IDs/names and matching cardinality before registration. Failures report stage/rule and safe status only; never raw subprocess exceptions, stderr, token-bearing JSON, environment dumps, or Terraform state. No new exception hierarchy or API error envelope is needed. |
| Observability | Reuse runner `alarms.tf`, `runner-health/*`, and network module flow logs/KMS/retention. `Shifter/RunnerHealth` missing-data alarms remain significant. Service-running is not DNS, egress, or GitHub job readiness; verify each separately. Preserve default-SG deny-all and private-only hosts, including externally supplied subnets. |
| Policy and schema gates | Reuse ADR guard, `check_tf_runner_network`, `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `.gitleaks.toml`, and ADR-004-R14 identifier hygiene. `validation-inventory.yaml` and `check_tf_roots` own the closed root/module/toolchain schema and committed provider locks. `.pre-commit-config.yaml`, `.github/quality-path-filters.yaml`, and `_quality.yml` own blocking coverage. No new validator, global skip, or weakened gate. |

## Concrete gaps and gotchas

- **A non-default VPC is not an IAM boundary.** `modules/provisioner-iam/main.tf`
  has wildcard-resource subnet/route and VPC-endpoint mutation grants. Its
  `ec2:Vpc` condition on `RunInstances` does not scope those other statements.
  Effective permissions also depend on boundaries/SCPs not established by this
  inspection. Do not describe the dedicated module as immune to range mutation
  until denied-path evidence exists. Any necessary narrow IAM correction belongs
  in that shared owner with its current policy tests, not a runner-local deny
  schema or a blanket condition applied to actions that do not support it.
- **Creation can fail before precedence helps.** Default-subnet discovery is
  currently counted from `allow_default_vpc` and empty `subnet_id`, independently
  of `create_runner_network`. Thus dev's retained opt-in can trigger unused
  discovery even when bootstrap creates an isolated network. Exercise a fresh
  account with no default VPC and no default subnets. Created IDs may be unknown
  at plan time; checks that require them can defer to apply, so do not promise
  all isolation evidence at plan time.
- **Private egress must be ready before first boot.** The network outputs
  reference VPC/subnet resources, not the completed NAT route/associations.
  Ensure the host dependency boundary covers usable egress before user data
  downloads packages/runner binaries. Validate IPv4 CIDR and derived AWS subnet
  sizes: the current `can(cidrhost(...))` check is not an IPv4-only or subnet-size
  guarantee. A subnet marked private or a NAT resource alone is insufficient.
  Retain connectivity for GitHub, package sources, ECR/S3, SSM, STS, EC2, and
  CloudWatch; public API NAT egress does not provide private EKS/portal access.
  Identify any such deploy dependency explicitly, without adding blanket peering.
- **The current network is single-AZ.** NAT/AZ failure stops that fleet; a reapply
  is recovery work, not high availability. Account for NAT/EIP quotas, recurring
  NAT/flow-log costs, CIDR overlap where connectivity exists, and endpoint/DNS
  drift. Do not copy the module comment claiming an AZ replacement is no outage.
- **Overrides and destroy must agree.** Explicit CLI `-var-file` / `-var` inputs
  can override auto-loaded local files. A gitignored file is not proof that its
  values win. The legacy wrapper uses committed backend placeholders and sources
  shell `.env`; consolidate through the incumbent bootstrap path instead of
  adding another override parser or copying token command examples. Teardown's
  `_runner_var_flags` currently infers default placement whenever the managed
  module is absent, which loses an explicit external network. Absence is not
  topology evidence. Preserve that third case and reject ambiguous state.
- **Current token redaction is insufficient.** AWS `runner.register_runner`
  embeds the registration token in JSON passed as local AWS CLI argv and retained
  SSM Run Command input. `run_cmd` can also print `CalledProcessError` and stderr
  with the original arguments. The remote PTY/0600 temporary-file handling only
  addresses remote argv; it does not fix those earlier layers. AWS explicitly
  advises against plaintext secrets in [Run Command inputs](https://docs.aws.amazon.com/systems-manager/latest/userguide/running-commands.html).
  Do not repeat the #1433 claim that normal-log masking satisfies the whole
  secret boundary. Registration transport hardening is separate from placement;
  safe migration must resolve this dependency before reusing that path with real
  tokens. `run_cmd_secret_stdin` supplies an existing local boundary, not an
  automatic solution to SSM history. Do not introduce a token store/broker here.
- **Replacing instances is a migration.** Drain active jobs; keep an external
  bootstrap/recovery path; preserve reviewed state and rollback inputs; handle
  GitHub name collisions/stale registrations and health alarms. Do not run the
  fleet's own replacement on the last runner it removes. Root names, IAM names,
  GitHub runner names, and the global state key are not tenant-unique within a
  shared account/backend; network CIDR parameterization does not solve that.
  The runner root's `tfplan` is not covered by the environment-only ignore rules;
  generated plans/outputs must remain protected local artifacts, never commits
  or ordinary CI artifacts.

## Extensibility and boundaries

Keep placement parameterized at the existing runner root: managed network via
`create_runner_network` / `runner_network_cidr`, or explicit `vpc_id` / `subnet_id`.
Keep region, account/backend, and runner identity coherent through `RunnerConfig`
and `RunnerTarget`. A future second AZ belongs in the network module's subnet/AZ
outputs and root placement mapping; it must not require new workflow booleans,
an application schema, or changes to credential transport. Do not introduce that
multi-AZ abstraction now. Portal placement must remain reversible and explicit,
with its external ownership and private access dependencies documented.

Implementation scope is the existing AWS runner root/module, their config and
lifecycle callers, any narrowly necessary shared IAM enforcement, existing
checker/test owners, and operator guidance. Reconcile the runner README,
`scripts/bootstrap/README.md`, and `docs/dev/{aws-runner-provisioning-runbook,
aws-terraform-apply-order,aws-teardown-runbook,deploy-secrets}.md`; update health
guidance if replacement changes it. Historical preflights are not evidence of
current defaults or safe token transport.

Non-goals: a new runner root, generic runner manager, autoscaler, CI routing
redesign, product deployment model, portal/range runtime redesign, disabling
range private DNS, DNS/hosts-file hacks, GCP/GDC/Kubernetes changes, new shared
schemas/services/repositories/exceptions, or a new secret-storage system. No
infrastructure is applied or migrated by this preflight, and no requirement,
issue, or PR is created or closed.

## Evidence required of implementation

Reuse `scripts/bootstrap/tests/{test_runner,test_bootstrap_core,
test_terraform_backend,test_aws_env_destroy}.py` and the runner-network checker
unittests. Cover effective configuration through all supported entry points,
fresh accounts without a default VPC, invalid/mismatched explicit placement,
explicit default opt-in only, unused discovery, and matching apply/destroy
topology. The existing regex guard proves expressions exist, not their behavior;
retain it and add behavioral coverage in the existing Terraform contract-test
conventions. The network module currently has a deferred contract in
`validation-inventory.yaml`; do not claim it already has executable tests.

For touched surfaces run ADR guard at CI level, the root-inventory check,
backendless locked-provider Terraform validation, recursive TFLint, canonical
Checkov/security checks, bootstrap tests, and actionlint if workflows change.
Static success is not adoption: operational evidence must show every eligible
runner's effective VPC/subnet, private egress and DNS independence with range
endpoints present, effective denied range mutations, SSM/GitHub readiness, health
signals, and an ordinary deployment after replacement. Keep live identifiers and
credentials out of committed evidence. Do not call #1437 complete while supported
entry points or active eligible runners silently retain the old placement.

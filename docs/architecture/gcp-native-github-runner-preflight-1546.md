# GCP-Native GitHub Runner Preflight (#1546)

Status: pre-implementation guidance; architecture decision required

Date: 2026-07-12

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1546>

This is a requirement-free preflight. The GitHub issue is the shipping
contract: provision and register a private GCE runner in the target GCP project,
without exposing its single-use GitHub registration token, and fail closed
unless the runner is online.

## Architecture Gate

The issue currently conflicts with accepted ADR-033-R2. ADR-033 classifies the
persistent CI/build/deploy runner fleet as development-plane and says it must
not reside in a deploy-target account. Issue #1546 explicitly requires that
fleet to reside in the GCP project being deployed. A separate Terraform state,
network, or service account reduces coupling but does not resolve the account
residency contradiction.

Do not begin implementation until one of these contracts is changed explicitly:

- revise #1546 to use maintainer-isolated runners or ephemeral target-project
  bootstrap compute, preserving ADR-033; or
- amend/supersede ADR-033-R2 with a deliberate target-project runner exception,
  its lifecycle/teardown consequences, and the operator-versus-maintainer
  ownership model.

This preflight does not silently choose the exception. If the issue is
explicitly retained as an ADR-033 exception, every guardrail below is binding.

There is a second activation gate. Most privileged workflows currently select
only `runs-on: self-hosted`. A newly online GCP runner with GitHub's default
labels could therefore pick up AWS deploy/build work before per-account routing
exists. Until routing is delivered, the GCP runner must register with
`--no-default-labels` and a custom, provider/environment-specific label set that
no existing workflow selects. It may be online for acceptance verification but
must remain schedulably inert. The routing follow-up must update workflow
selection and teach the ADR-003-R5 runner-exposure check to recognize the custom
self-hosted label before any workflow starts using it.

## Scope And Ownership Boundaries

Keep these concerns separate:

1. GCP runner infrastructure owns the custom VPC, subnet, Cloud NAT, firewall,
   service account, GCE instances, non-secret startup configuration, and
   Terraform outputs.
2. Bootstrap orchestration applies that root, waits for the host to become
   registration-ready, mints one GitHub token per runner, performs the IAP/SSH
   handoff, and verifies GitHub status.
3. GitHub registration exchanges a short-lived token for the runner's intended
   long-lived `.runner` / `.credentials` files. Terraform and GCP control-plane
   services never handle the token.
4. Workflow routing decides which jobs may select the fleet. It is a separate
   trust decision and must not be inferred from successful registration.
5. Steady-state health/alerting is separate from registration completion. A
   long-lived GitHub API poller or PAT on the VM is not part of this issue.

If the ADR conflict is resolved in favor of #1546, the GCP runner must use a
separate Terraform execution root and state prefix from the `gcp-dev` platform
root. The platform destroy workflow must not accidentally destroy runner state
or resources. This preserves bootstrap ordering, but it does not claim that a
whole-project deletion can preserve an account-local runner.

Use a custom-mode, non-default VPC with a private runner subnet, Private Google
Access, a reserved Cloud NAT egress address, subnet flow logs, and no peering to
the platform or range VPCs. Instances have no external IP. SSH ingress is TCP/22
from Google's IAP range only and targets the runner service account. The stable
NAT address is also the natural future input to GKE master-authorized networks;
do not couple the runner VPC to the GKE or range network to obtain reachability.

Use IAP/OS Login for registration. The startup script installs a pinned runner
version and checksum plus the required host toolchain, but carries no token and
does not self-register. Do not select the issue's startup-script secret-handoff
alternative: the explicit prohibition on Terraform state, instance metadata,
Secret Manager persistence, argv, and logs leaves IAP/SSH stdin as the smaller
and auditable secret surface.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse / boundary |
| --- | --- | --- |
| Issue/ADR authority | ADR-033 / `docs/architecture/product-development-surfaces.md` | Resolve the target-project residency conflict explicitly. A separate root is not an implicit exception. |
| Bootstrap command surface | `scripts/bootstrap/cli.py`, `deploy.py` compatibility facade, `preflight.py` | Extend the existing CLI and `Cloud.GCP` preflight path; do not create a second deployment CLI. Keep AWS command behavior stable. |
| Runner lifecycle | `scripts/bootstrap/runner.py` | Reuse/adapt token minting, GitHub verification, failure aggregation, target naming, labels, and dry-run behavior. Keep GCP transport provider-specific; do not copy the whole lifecycle into unrelated GCP bootstrap modules. |
| Command validation/logging | `bootstrap_core.py` `run_cmd`, `_validate_argv`, `_redact_argv_for_log` | Add the minimum secret-stdin/error-redaction capability here. Do not bypass it with scattered raw `subprocess` calls or shell strings. |
| AWS registration precedent | `docs/architecture/github-runner-bootstrap-automation-preflight-1433.md`, `runner.py` | Preserve one token per target, memory-only lifetime, no Terraform/user-data secret, bounded verification, and fail-closed completion. Reuse policy, not SSM-specific fields. |
| IAP argv precedent | `scripts/bootstrap/gdc_cluster.py` `wait_for_gdc_ssh` / `run_gdc_workstation_script` | Reuse `gcloud compute ssh --tunnel-through-iap` argv construction and bounded readiness polling. Do **not** copy its project SSH-key metadata or `enable-oslogin=FALSE`; runner access requires OS Login and blocked project keys. |
| GCP network precedent | `platform/terraform/gcp/modules/{portal,range}/vpc`, `cicd-github-oidc/build-infra.tf`, `docs/architecture/gcp-vpc-firewall-preflight.md` | Reuse custom-network, private subnet, reserved Cloud NAT, flow-log, IAP-range, service-account-targeted firewall, and explicit-policy conventions without importing platform/range semantics. |
| GCP backend convention | `platform/terraform/gcp/environments/gcp-dev/backend.tf`, `_gcp-dev.yml`, `GDCBootstrapConfig.terraform_state_bucket_name` | Reuse `${project_id}-terraform-state` and a dedicated runner prefix. Do not add runner resources to the platform state or copy the workflow's bucket bootstrap shell into another workflow. |
| Terraform ownership/validation | `platform/terraform/validation-inventory.yaml`, `scripts/check_tf_roots`, `.tflint.hcl`, `platform/terraform/.checkov.yaml` | Register the new execution root, commit its lockfile, use the GCP toolchain profile, and keep backendless validation plus blocking Checkov/TFLint. |
| GitHub target | `.ground-control.yaml` `github_repo`, existing bootstrap GitHub defaults | Default to `Brad-Edwards/shifter`; do not derive the target from remotes or add a second repo schema. |
| Workflow trust | ADR-003-R5, `scripts/adr_guard/adr_guard.py` `deploy-workflow-runner-exposure`, trusted GCP environment binding | No pull-request reachability, no implicit scheduling via generic labels, and no custom-label blind spot once routing activates. |
| GCP deploy auth | `_gcp-dev.yml` Workload Identity Federation | Jobs continue to obtain deploy credentials through OIDC. The VM service account is not a substitute deploy identity and receives no broad project mutation role. |
| Operator docs | `scripts/bootstrap/README.md`, `docs/dev/deploy-secrets.md`, `docs/technical/platform_infrastructure/github-runners.md`, `docs/index.md` | Extend the existing bootstrap/runner documentation surfaces after the architecture gate is resolved; do not create a disconnected runbook taxonomy. |

No application controller, DTO, Django schema, repository, database model,
shared cloud task runner, exception hierarchy, or runtime secret store solves
part of this problem. Pulling those layers into runner bootstrap would be
concept leakage.

## Cross-Cutting Layers The Intended Design Must Pass

- **GitHub authentication.** Use the repository registration-token endpoint
  through the operator's existing `gh` authentication. Preflight must require
  `gh` and fail before Terraform mutation when GitHub authentication cannot mint
  for the configured repository. Mint once per runner, use once, retain in
  process memory only, and never include API response bodies in an error.
- **Bootstrap input shapes.** Project, environment, region, zone, runner count,
  network CIDR, machine type, image, runner version/checksum, repo identity,
  work folder, and routing labels are explicit typed/configured inputs. Validate
  non-empty identifiers, positive counts, valid non-overlapping RFC1918 CIDR,
  supported architecture, immutable runner version/checksum, and a custom label
  set that excludes `self-hosted` until routing activation. Do not reuse
  `RunnerConfig.aws_profile` or `RunnerTarget.instance_id/region` as misleading
  GCP fields.
- **Terraform/state shape.** Terraform receives infrastructure configuration
  only. No registration/removal token, GitHub PAT, SSH private key, generated
  credential, or secret-bearing startup script may appear in a variable, local,
  output, plan, state, tfvars file, backend config, or provisioner block. Outputs
  are bounded target metadata: project, zone, instance name, runner name, labels,
  and NAT address.
- **GCP control-plane authorization.** The operator's gcloud/ADC identity applies
  Terraform and opens IAP/OS Login sessions. Do not reuse the GDC Terraform
  bootstrap service account/key path: it temporarily grants `roles/owner` and is
  the wrong boundary for a runner. Required IAP and OS Login rights belong to an
  explicit operator principal; the attached VM service account is dedicated and
  least-privilege (at most host logging/monitoring needs), never the project
  default service account and never the deploy identity.
- **Network policy.** Reject default-network placement. The instance is
  private-only, egresses through the dedicated static Cloud NAT, and admits only
  IAP SSH targeted by service account. No public IP, world-open SSH, broad
  internal allow, platform/range peering, or reuse of range/packer subnets.
  Firewall and subnet logging must not include application payloads or tokens.
- **GCE metadata/startup.** Metadata is limited to static non-secret hardening
  and bootstrap configuration. Enable OS Login, block project-wide SSH keys,
  disable legacy metadata endpoints/serial-port access, and use Shielded VM
  controls. The startup script may install packages and the checksum-pinned
  Actions runner only. It must not call GitHub's registration API, receive a
  token, or emit a credential in cloud-init/serial logs.
- **OS/process exposure.** Extend `run_cmd` (or its focused incumbent) to accept
  secret stdin without rendering it. Invoke `gcloud compute ssh` with a static,
  non-secret remote command and feed the token over the SSH stdin stream to
  interactive `config.sh`; never use `--token <value>`, environment variables,
  heredocs embedded in `--command`, temp files, `gcloud compute scp`, metadata,
  or Secret Manager. Keep tracing disabled and start the service only after
  registration succeeds.
- **Error/log envelope.** `run_cmd` currently prints captured stderr verbatim on
  failure and has no stdin-input contract. A secret-input path must suppress or
  sanitize raw child output and report only stage, runner name, project/zone,
  bounded exit status, and remediation. Never print the token, stdin, remote
  command output, environment, Terraform state/plan, metadata, `.runner`, or
  `.credentials`.
- **Readiness and verification.** A running GCE instance is not registration
  readiness. Poll IAP/SSH and a non-secret on-host readiness probe with a bounded
  timeout. Success requires both a zero registration/service-start result and a
  bounded GitHub API poll reporting the expected runner online with the expected
  provider/environment labels. Name-only verification can be fooled by a stale
  runner and is insufficient. Any unknown/timeout/offline/mismatched-label state
  fails the command.
- **Scheduling/trust.** Before the routing follow-up, register with
  `--no-default-labels` and labels no workflow selects. When routing activates,
  update both workflow selectors and ADR-003-R5 enforcement so custom self-hosted
  labels cannot bypass pull-request exposure checks. Keep GCP deploy Environment
  binding and WIF; do not grant deployment privilege to the VM service account.
- **Static policy.** The eventual change must pass ADR guard, Terraform root
  inventory, backendless locked init/validate, Terraform fmt, Google TFLint,
  blocking Checkov, gitleaks/pre-commit, and focused bootstrap tests. Workflow
  or guard changes additionally require actionlint and matching ADR evidence or
  exception metadata; do not soften a gate to admit the new root.

## Extensibility Seam

Keep common orchestration parameterized by repository identity, runner name,
work folder, routing labels, and verification policy. Keep provider transport
data provider-specific: AWS uses instance id/region/SSM; GCP uses
project/zone/instance name/IAP. Do not create a generic “cloud command” or a
single target DTO full of optional AWS/GCP fields.

For GCP infrastructure, the required variation seam is:

`(project_id, environment, region, zone policy, runner_count,
runner_network_cidr, machine_type, runner_version, runner_checksum,
routing_labels)`.

The next expected variation is `gcp-prod`, another project/zone, or a routed
label set. It should change values/target mapping, not duplicate the Terraform
root, token handoff, or verification lifecycle. Image and runner version must
be explicit so a routine upgrade does not require editing startup-script logic.

## Whole-Repository Surfaces In Scope After The Gate Is Resolved

- `scripts/bootstrap/{cli.py,deploy.py,runner.py,bootstrap_core.py,preflight.py,README.md}`
  and focused tests.
- A dedicated GCP runner Terraform root/module under `platform/terraform/gcp/**`,
  its committed provider lockfile, and `platform/terraform/validation-inventory.yaml`.
- Existing GCP backend/state bootstrap conventions in `_gcp-dev.yml` and
  `gcp-dev-destroy.yml`; edits are warranted only to remove duplication or
  preserve separate runner lifecycle, not to route jobs prematurely.
- `scripts/adr_guard/adr_guard.py`, tests, ADR-003 evidence, and GCP workflows
  when custom-label routing is activated.
- ADR-033 and `docs/architecture/product-development-surfaces.md` if the issue's
  target-project residency is retained.
- Runner/bootstrap/operator documentation and documentation-coverage metadata
  required by ADR-022 when the feature ships.

Application code under `shifter/shifter_platform`, range-cell/GDC provisioning,
Kubernetes runtime manifests, portal secrets, and database persistence are out
of scope.

## Gotchas And Anti-Patterns

- Do not treat the issue number as an implicit override of ADR-033 or claim a
  separate state prefix cures target-account lifecycle coupling.
- Do not bring up a runner with default `self-hosted` labels before account
  routing. It can accept unrelated AWS jobs immediately.
- Do not hide the GCP runner behind custom labels without extending the
  ADR-003-R5 exposure checker when workflows begin selecting those labels.
- Do not pass the token through Terraform, startup scripts, instance/project
  metadata, Secret Manager, an environment variable, a temp file, `scp`,
  `--command`, `--token`, shell history, stdout/stderr, or test snapshots.
- Do not copy GDC's project SSH-key metadata or `enable-oslogin=FALSE` pattern.
  IAP transport is reusable; that weaker host-auth shape is not.
- Do not attach the project default service account, `roles/owner`, Editor, or
  deploy roles to the runner VM. Workflow WIF remains the deployment identity.
- Do not query GitHub from the VM with a PAT and do not persist a GitHub token
  merely to implement health checking.
- Do not download “latest” Actions runner code without an immutable version and
  checksum. Do not make the base image/startup path silently architecture-specific.
- Do not declare success on Terraform apply, VM `RUNNING`, successful SSH, or
  GitHub name presence alone. Registration command status, online state, and
  expected labels are all required.
- Do not duplicate token mint/verify/failure logic, GCS backend naming, gcloud
  argv validation, Terraform root registration, or firewall conventions.
- Do not create a provider-neutral runner IaC module, generic cloud exception
  hierarchy, new secret store, runner database, controller, or autoscaler for
  this issue.

## Non-Goals And Implementation Boundaries

- This preflight does not implement #1546 and does not amend ADR-033 without an
  explicit product/development-plane decision.
- No per-account workflow-routing rollout in #1546 unless the issue is expanded;
  custom labels keep the new runner inert until that follow-up lands safely.
- No AWS runner migration, shared AWS/GCP Terraform root, or change to SSM
  registration semantics.
- No autoscaling, ephemeral-job runner controller, GitHub App, ARC, webhook,
  persistent token broker, or stored PAT.
- No registration/removal-token conflation. Deregistration and replacement are
  separate lifecycle work.
- No GKE, range VPC, GDC, portal, application schema, runtime secret, or
  database change.
- No steady-state GitHub-online poller. If host/service monitoring is added,
  use native Cloud Monitoring with non-secret local service state; do not add a
  second cross-cloud observability abstraction in this issue.

## Validation Expectations

For this preflight documentation change:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

The eventual implementation also needs focused tests proving that secret stdin
never reaches argv/logs/errors, dry-run mints no token and opens no SSH session,
Terraform inputs contain no token, default labels are absent before routing,
stale-name/mismatched-label verification fails, readiness and online polling are
bounded, and every failed/unknown registration state exits non-zero.

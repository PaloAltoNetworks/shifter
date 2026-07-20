# AWS Range Guest AMI DNS Preflight (#1633)

Status: pre-implementation guidance

Date: 2026-07-14

Issue #1633 is the shipping contract. This is a requirement-free run. This
note does not implement guest DNS, rebuild an AMI, or update an SSM parameter.

## Decision Boundary

The durable owner of baseline AWS guest DNS is the AWS AMI build. Range
Terraform owns VPC DHCP, Route 53 Resolver policy, the instance profile, and
the temporary Linux user-data mitigation from #1632. The provisioner owns
post-boot setup, including the intentional switch of a domain member's DNS to
its DC. These responsibilities must not be merged into a second resolver,
image registry, setup plan, or runtime configuration schema.

No ADR change is needed while the fix stays inside the existing Packer, range
DNS, SSM, and pre-promoted-DC boundaries. A new ADR is needed only if the work
changes the authoritative resolver, permits public recursive DNS, changes DC
promotion ownership, or moves AMI publication away from `/shifter/ami/*`.

## Architecture Decisions And Guardrails

- Apply the baked policy only to the top-level AWS `amazon-ebs` sources for
  `kali`, `ubuntu`, `windows`, and the actual pre-promoted `dc` artifact. The
  Linux and Windows base scripts are also consumed by GCP templates, and the
  Windows base script is consumed by the un-sysprepped `polaris-dc` build. An
  AWS resolver change must therefore be an AWS-only provisioner or be guarded
  by an explicit image/provider profile; it must not leak through a nominally
  shared script.
- Linux keeps `systemd-resolved` as the system resolver. Preserve DHCP-derived
  per-link DNS when the network manager supplies it, and bake
  `169.254.169.253` as the deterministic fallback available from resolver
  startup. `FallbackDNS=` preserves per-link precedence; a static
  `/etc/resolv.conf`, a public resolver, or two daemons managing the same link
  is not an acceptable fix. Assert the service, the intended `resolv.conf`
  mode, a non-empty upstream set, and real resolution during the bake and on a
  fresh boot.
- Windows Server 2022 uses EC2Launch v2 as its first-boot owner. The AWS-only
  image configuration must establish or verify DNS in an EC2Launch `PreReady`
  task before the existing `PostReady` `startSsm` task. Use the active
  DHCP-enabled adapter set; do not bake a builder interface index, interface
  alias, adapter GUID, VPC CIDR, or DC address. Validate the resulting
  `agent-config.yml` with `EC2Launch.exe validate` before sysprep.
- A Windows DNS task must be first-boot scoped, not an `always` task that resets
  DNS after every reboot. `DomainJoinPlan` deliberately replaces DHCP DNS with
  the DC address before joining a Windows victim. Reapplying AmazonProvidedDNS
  after that transition would break AD discovery. `DCSetupPlan` and the
  pre-promoted image remain the owners of DC DNS service/forwarding after AD is
  active.
- `/shifter/ami/dc` is a pre-promoted DC contract. Runtime promotion is
  intentionally disabled in `state_helpers._should_promote_dc_at_runtime`, and
  `DCSetupPlan` verifies an existing forest. The current `dc.pkr.hcl` only
  installs AD DS/DNS features, while `packer-promote.yml` still publishes the
  checked-in pre-promoted ID from `dc-amis.json`. Do not publish the generalized
  `dc.pkr.hcl` result as `/shifter/ami/dc`; the DNS fix must be applied to and
  validated against the actual pre-promoted `internal.shifter` artifact.
- Keep the #1632 Linux user-data pin during initial rollout. It is idempotent
  defense in depth, and removing it at the same time would erase the fallback
  before exact-candidate boot evidence exists. A later removal must update its
  structural tests and be justified by repeated fresh-boot evidence.
- Both the VPC-plus-two address currently delivered by range DHCP and
  `169.254.169.253` reach AmazonProvidedDNS. This retains the Route 53 Resolver
  DNS Firewall allowlist and query logging in the range VPC. Do not use
  `8.8.8.8`, `1.1.1.1`, or another public resolver as a fallback.
- A successful Packer provisioner run is not publication evidence for a
  first-boot race. The exact AMI ID extracted from the same-run manifest must
  boot in a runtime-equivalent range VPC with the range instance profile,
  register with SSM, execute the correct Run Command document, resolve the
  regional SSM private name through the system resolver, reboot, and pass the
  same checks again. Failure or missing evidence leaves the old SSM value
  untouched.
- Keep the build, verification, manifest upload, cleanup, and SSM publication
  in `.github/workflows/packer.yml`. Reuse the disposable-instance lifecycle,
  bounded polling, `::error::` annotations, and cleanup conventions already in
  `scripts/bake/golden-verify.sh`; do not force base-OS DNS checks into its
  scenario-container health model or create another AMI workflow family.
- The agent-free post-deploy smokes remain end-to-end evidence after dev
  publication: `smoke_linux` forces both Kali and Ubuntu through provisioning,
  and `smoke_windows` covers a plain Windows victim. They are advisory and do
  not bind an exact candidate before publication, so they cannot replace the
  candidate boot gate. DC acceptance additionally needs the existing
  pre-promoted forest/DNS verification path.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| AWS image build | `shifter/packer/{kali,ubuntu,windows,dc}.pkr.hcl`, `variables.pkr.hcl`, environment pkrvars | Keep source names, `-only` selectors, manifest names, and environment bindings aligned. |
| Provider boundary | Top-level `shifter/packer/` versus `shifter/packer/gcp/`; shared script references in the GCP HCL | Keep Amazon resolver and EC2Launch changes out of GCE/GDC images. |
| Windows image lifecycle | `scripts/windows/sysprep.ps1`, EC2Launch v2, `polaris-dc.pkr.hcl`, and `dc-amis.json` | Preserve generalized versus pre-promoted semantics; do not infer them from `PACKER_ROLE=dc`. |
| Range DNS control plane | `platform/terraform/modules/range/vpc/{main.tf,dns_resolver.tf,ssm-endpoints.tf}` | Reuse VPC DNS support, DHCP-to-AmazonProvidedDNS, DNS Firewall/query logs, and private SSM endpoints. |
| Range host identity | `platform/terraform/modules/range/vpc/iam.tf` and `RANGE_INSTANCE_PROFILE_NAME` wiring | Use the existing SSM-enabled range profile for live validation; add no guest Parameter Store read grant. |
| AMI lookup/persistence | `provisioner_ami.py`, `terraform_vars.py`, portal SSM data sources | Keep `/shifter/ami/{kali,ubuntu,windows,dc}` as the only runtime pointer. No database image inventory or new DTO is needed. |
| Guest setup errors | `SSMExecutor.wait_for_ready`, `verify_agent_ready`, `SetupError`, and setup-orchestrator output bounds | Prove Run Command readiness, retain bounded diagnostics, and use existing runtime failure/cleanup behavior. |
| Domain DNS transition | `plans/domain_join.py`, `plans/dc_setup.py`, and `dc_setup.py` | Keep member DNS switching and pre-promoted forest/DNS verification out of Packer's baseline DNS policy. |
| Build verification | `scripts/bake/golden-verify.sh`, `shifter/packer/tests/test_packer.py`, and `test_scripts.sh` | Reuse lifecycle conventions; add focused OS-aware checks to the existing Packer test surface. |
| End-to-end smoke | `run_post_deploy_smoke`, `smoke_linux.yaml`, and `smoke_windows.yaml` | Use existing range create/readiness/probe/teardown behavior; do not add a DNS-specific CMS service or schema. |
| Workflow gates | `_quality.yml` Packer lint/SAST/tests, `actionlint`, and ADR guard | Preserve existing path routing and fail-closed checks. Add a `1633.fixed.md` fragment for the user-visible operational fix. |

## Cross-Cutting Layers The Design Must Pass

### Security and configuration

- **Workflow authorization:** continue using SHA-pinned actions and GitHub OIDC
  roles; add no static AWS key or PAT. The base job currently checks out a
  free-form `ref` before assuming a deploy role. If this privileged workflow is
  changed for candidate validation, restrict that ref to protected branches or
  fail closed on a tight allowlist before AWS authentication.
- **Input shapes:** reuse the existing choice inputs for `ami_type` and
  `environment`, and the scenario job's strict subnet, security-group,
  instance-profile, instance-type, and SSM-name validation if those existing
  inputs are widened for base-candidate validation. Bind dynamic Packer values
  through `PKR_VAR_*`, not shell interpolation or `-var` argv.
- **Packer and OS validators:** `packer validate` protects HCL/source shape;
  shell strict mode and ShellCheck protect Linux scripts; PowerShell must use
  fail-closed `$ErrorActionPreference`; `EC2Launch.exe validate` protects the
  boot-task schema. Static tests must also prove DNS configuration precedes SSM
  startup and that AWS-only scripts are absent from GCP and pre-promoted
  scenario sources.
- **Secret handling:** resolver IPs, AMI IDs, instance IDs, and SSM parameter
  names are non-secret diagnostics. Role credentials, STS tokens, generated
  Windows passwords, DC credentials, private keys, and full remote command
  output must not enter Packer vars, argv, manifests, AMI metadata, workflow
  summaries, or evidence artifacts. The DNS fix needs no secret or new env
  setting.
- **OS/network exposure:** candidate validation should use the no-inbound SSM
  path and IMDSv2 posture already used by golden verification. It must not open
  SSH, WinRM, or RDP merely to inspect DNS. The existing public, unencrypted
  WinRM builder communicator is a separate hardening concern; do not copy or
  widen it as part of validation.
- **Resolver policy:** only AmazonProvidedDNS is allowed. Private SSM endpoint
  names must continue to resolve through the VPC resolver so DNS Firewall and
  query logging remain authoritative; a hosts-file entry or direct endpoint IP
  would bypass the intended contract.

### Errors, logs, and persistence

- Guest configuration fails the Packer build on an unsupported resolver stack,
  an invalid EC2Launch config, an empty upstream set, or a failed resolution
  check. Do not hide these with `|| true`, `SilentlyContinue`, or a warning-only
  branch on the shipping path.
- Live verification uses bounded polls and always terminates the disposable
  instance. Report the AMI type/ID, instance ID, OS family, failed check, and a
  bounded resolver/EC2Launch status excerpt. Do not upload full cloud-init,
  journal, EC2Launch, SSM, or environment dumps.
- Runtime failures continue through the existing SSM executor, setup
  orchestrator, CMS status, cleanup, and sanitized error surfaces. No DNS
  exception hierarchy or public error envelope is needed.
- Route 53 Resolver query logs and guest service logs are operational evidence;
  `/shifter/ami/*` is the only durable publication state. Do not add a model,
  migration, repository, Redis key, or second parameter namespace.

## Extensibility Seam

The seam is an allowlisted AWS base-image verification profile keyed by the
existing `ami_type`. Each profile selects the OS-aware remote document and
checks while sharing exact-candidate launch, SSM polling, reboot, evidence, and
cleanup mechanics. Windows image lifecycle (`generalized` versus
`pre-promoted`) remains an explicit Packer-source property, not a value inferred
from the guest role.

That lets a later AWS image such as `brokenbk` opt into the Linux DNS policy by
adding one profile and one source reference. It does not require another
workflow, AMI resolver, provider-neutral DNS schema, or edits to GCP images.

## Whole-Repo Scope

The implementation may need to touch:

- `shifter/packer/{kali,ubuntu,windows,dc}.pkr.hcl` and AWS-only guest DNS
  scripts under `shifter/packer/scripts/`;
- `shifter/packer/tests/test_packer.py`, `test_scripts.sh`, and `README.md`;
- `.github/workflows/packer.yml` for exact-candidate verification before dev
  SSM publication;
- `.github/workflows/packer-promote.yml`, `dc-amis.json`, and
  `docs/technical/platform_infrastructure/ami-management.md` only as needed to
  reconcile the pre-promoted DC artifact and exact validated candidate;
- `docs/dev/aws-ami-seeding-runbook.md` for the resulting operator validation
  and publication contract; and
- `changelog.d/1633.fixed.md`.

Guardrails to inspect but normally not edit:

- `shifter/engine/provisioner/terraform/modules/range/main.tf` and
  `tests/test_range_tf_userdata_dns.py` (#1632 defense in depth);
- `platform/terraform/modules/range/vpc/{main.tf,dns_resolver.tf,iam.tf,ssm-endpoints.tf}`;
- `shifter/engine/provisioner/{provisioner_ami.py,terraform_vars.py,dc_setup.py}`
  and `plans/{domain_join.py,dc_setup.py}`;
- `shifter/shifter_platform/cms/post_deploy_smoke/**` and the two smoke scenario
  templates;
- `shifter/packer/gcp/**`, `polaris-dc.pkr.hcl`, and shared base scripts as
  provider/lifecycle boundaries that must not regress; and
- `_quality.yml`, `.github/quality-path-filters.yaml`, pre-commit, actionlint,
  and ADR guard as existing enforcement.

## Gotchas And Anti-Patterns

- Do not put AmazonProvidedDNS into a shared script consumed by GCP.
- Do not mistake `PACKER_ROLE=dc` for the image lifecycle; generic DC and
  pre-promoted `polaris-dc` both use it.
- Do not publish the feature-only `dc.pkr.hcl` image to the verify-only DC
  runtime contract.
- Do not use a Windows `always` boot task that undoes domain-join DNS.
- Do not hard-code a builder NIC identity or VPC-plus-two address into an AMI.
- Do not replace the resolved stub with a static file or run networkd,
  NetworkManager, and dhclient as competing owners.
- Do not treat `systemctl is-active`, `PingStatus=Online`, Packer success, or an
  open SSH/RDP port alone as proof. Resolution and a real Run Command must pass
  on the exact candidate after a reboot.
- Do not update SSM before validation, validate “latest” instead of the manifest
  AMI, or let a failed validation overwrite the previous known-good pointer.
- Do not make the advisory post-deploy smoke the only publication gate.
- Do not add DNS fields to scenario YAML, range DTOs, Terraform variables, app
  settings, or environment manifests; the AWS resolver is infrastructure, not
  participant intent.

## Non-Goals

- No implementation, AMI build, cloud mutation, or SSM update in this preflight.
- No GCP/GDC image change, scenario-image DNS redesign, or public resolver.
- No removal of the #1632 mitigation during the initial durable rollout.
- No runtime DC promotion, AD/domain schema redesign, or domain-join rewrite.
- No new workflow family, image registry, API, service, DTO, repository,
  persistence model, logging framework, or exception hierarchy.
- No unrelated WinRM communicator, package provenance, AMI encryption, or
  cross-account promotion redesign. Existing weaknesses may be handled in
  focused work, but this fix must not deepen them.

## Validation Expectations

Static implementation checks include:

```bash
cd shifter/packer
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
bash tests/test_scripts.sh
packer validate -var-file=dev.pkrvars.hcl -only='*.kali' .
packer validate -var-file=dev.pkrvars.hcl -only='*.ubuntu' .
packer validate -var-file=dev.pkrvars.hcl -only='*.windows' .
packer validate -var-file=dev.pkrvars.hcl -only='*.dc' .
```

Run `actionlint` for workflow edits and the repository-required
`python3 scripts/adr_guard/adr_guard.py --all --level ci` gate. Static checks do
not replace the exact-candidate fresh-boot/reboot verification and the existing
Linux, Windows, and pre-promoted-DC runtime smokes.

## Authoritative Behavior References

- [AmazonProvidedDNS addresses and behavior](https://docs.aws.amazon.com/vpc/latest/userguide/AmazonDNS-concepts.html)
- [systemd-resolved global and fallback DNS precedence](https://www.freedesktop.org/software/systemd/man/devel/resolved.conf.html)
- [EC2Launch v2 stage and default `startSsm` ordering](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2launch-v2.html)
- [EC2Launch v2 task schema and validation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2launch-v2-settings.html)
- [Windows DHCP DNS reset behavior](https://learn.microsoft.com/powershell/module/dnsclient/set-dnsclientserveraddress)

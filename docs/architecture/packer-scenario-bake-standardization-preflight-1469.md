# Packer Scenario Bake Standardization Preflight (#1469)

Status: pre-implementation guidance

Date: 2026-07-13

Issue: GitHub #1469, "Standardize all AMI builds on Packer; retire the SSM
scenario-bake workflows [tracking]"

This is a requirement-free maintenance issue. The GitHub issue is the shipping
contract. This note records the repository-wide architecture boundary and
guardrails only; it is not an implementation plan.

## Boundary And Decision

All AWS AMI production paths should converge on the existing Packer surface
under `shifter/packer/` and `.github/workflows/packer.yml`.

The durable boundary is:

- Packer templates own builder launch, guest provisioning, image creation,
  manifest emission, and native builder teardown.
- GitHub Actions owns operator dispatch, cloud authentication, Packer
  invocation, post-build verification, artifact upload, and SSM publication.
- The range provisioner and scenario templates remain AMI consumers. They
  resolve logical `ami_key` values through `/shifter/ami/<key>` and must not
  learn how a specific AMI was baked.

`polaris-dc` is already an AWS Packer build. The missing AWS scenario builds
are the Linux scenario hosts currently baked by
`.github/workflows/polaris-scenario-bake.yml` and
`.github/workflows/techvault-scenario-bake.yml`. Migrate those to Packer rather
than preserving the hand-rolled `run-instances` / SSM shell driver /
`create-image` lifecycle.

Keep golden verification as a post-build workflow gate: launch a fresh instance
from the produced AMI, prove the participant contract, then publish the SSM
parameter. SSM publication is success-only and after encryption verification.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| AWS Packer build surface | `shifter/packer/*.pkr.hcl`, `variables.pkr.hcl`, `dev.pkrvars.hcl`, `proof.pkrvars.hcl`, `.github/workflows/packer.yml` | Add scenario AWS sources here. Keep source names, manifest names, workflow choices, artifact names, and `/shifter/ami/<key>` names aligned. |
| Packer quality gates | `shifter/packer/tests/test_packer.py`, `test_packer_gcp.py`, `pyproject.toml`, `_quality.yml` `packer-lint`, `packer-sast`, `packer-tests` | Encode new source/lifecycle/workflow invariants in the existing tests. Do not add a separate one-off shell validator if the invariant belongs in Packer tests. |
| Builder lifecycle guardrail | `docs/architecture/packer-builder-termination-preflight-342.md`, Packer `run_tags.Name`, workflow cleanup | Preserve Packer-owned lifecycle and controlled builder tags. Scenario builders should not resurrect ad hoc orphan cleanup maps. |
| TechVault bake contract | `docs/ops/techvault-bake-runbook.md`, `docs/architecture/techvault-encrypted-ami-preflight-1455.md`, `.github/workflows/techvault-scenario-bake.yml` | Preserve `aptl lab start`, full-stack convergence, running-stack image semantics, encrypted root volume proof, and fresh-AMI golden verify. |
| Polaris bake contract | `docs/architecture/polaris-scenario-bake-preflight-618.md`, `scripts/polaris-aws-range/**`, `check_range_health.py`, `range_health.py` | Preserve external tarball sourcing, 17-container health contract, per-range `/28` isolation model, and scenario smoke evidence. |
| AMI consumer contract | `shifter/engine/provisioner/provisioner_ami.py`, `terraform_vars.py`, scenario `ami_key` fields | Continue resolving `techvault`, `polaris-vm`, and `polaris-dc` through `/shifter/ami/<key>`. Do not commit AMI IDs to scenario YAML, Terraform variables, or application config. |
| Runtime per-range setup | `TechVaultRangeBootstrapPlan`, `PolarisRangeBootstrapPlan`, `SetupOrchestrator`, `SSMExecutor` | Keep per-range credentials, DC IP rewrites, Bedrock/Vertex shards, and verification in provisioner setup plans. Do not bake participant-specific or range-specific material. |
| AWS OIDC/IAM owner | `platform/terraform/global/iam/github-oidc.tf` | Reuse the existing GitHub OIDC role policy surface. If Packer SSM/session-manager builders require extra AWS actions or `iam:PassRole`, add them narrowly here instead of creating static credentials or parallel workflow roles. |
| Range launch security gate | `platform/terraform/modules/engine-provisioner/iam.tf` | Preserve account-owned AMI scope and `ec2:Encrypted=true` root-volume launch enforcement. Do not weaken provisioner IAM to compensate for a bad bake. |
| Operator helper | `scripts/ami.sh` | Keep its accepted AMI types aligned with `packer.yml`; it should not mention AMI choices that lack AWS Packer sources. |
| Workflow quality and release hygiene | `actionlint`, `scripts/adr_guard/adr_guard.py`, `.gc/plan-rules.md`, `changelog.d/README.md` | Workflow edits must pass actionlint and ADR guard. Pipeline behavior changes need a changelog fragment; do not edit `CHANGELOG.md` directly. |

## Required Cross-Cutting Layers

### Security

- GitHub auth surface: keep privileged AMI builds `workflow_dispatch` only,
  `permissions: id-token: write, contents: read`, and
  `aws-actions/configure-aws-credentials`. Do not add push, pull request,
  schedule, long-lived AWS keys, PATs, or branch inputs that let an operator run
  unreviewed code with bake credentials.
- Workflow input shape: use choice inputs where possible. Any free-form value
  that reaches Packer variables, AWS CLI filters, S3/GCS object names, SSM
  names, tags, or shell must be bound through environment variables and
  validated against an allowlist before use.
- Packer variable shape: keep required variables in `variables.pkr.hcl` and
  environment/account values in `*.pkrvars.hcl` or validated `PKR_VAR_*`
  bindings. Do not hide missing bake inputs behind broad defaults.
- Packer SSM/session-manager builder access: scenario builders should use a
  no-inbound path. The builder instance profile must be explicit and limited to
  the build needs such as SSM management plus read access to the scenario
  artifact bucket. Do not open SSH/RDP ingress solely for the bake.
- Secret handling: Packer vars, workflow inputs, SSM String AMI parameters, AMI
  tags, step summaries, and manifests may contain non-secret AMI IDs, SSM names,
  KMS aliases, bucket/key names, and instance IDs. They must not contain AWS
  secret keys, STS session tokens, CTFd admin tokens, SSH private keys, RDP
  passwords, static Bedrock credentials, or generated Windows passwords.
- OS/process exposure: avoid putting untrusted or sensitive values into process
  argv through `packer -var ...` or shell-expanded workflow inputs. Prefer
  `PKR_VAR_*` environment binding for dynamic values, quote all shell
  references, and keep Packer shell provisioners under `set -euo pipefail`.
- Encryption gate: every published scenario AMI must prove all EBS block-device
  mappings are encrypted before `/shifter/ami/<key>` is updated. This preserves
  the range provisioner's `ec2:Encrypted=true` fail-closed behavior.
- Error/report envelope: use GitHub `::error::` annotations and step summaries
  with non-secret identifiers. Packer or golden-verify failure must stop before
  SSM publication.

### Maintainability

- Reuse `packer.yml` rather than adding another bake workflow family. If the
  workflow becomes too branchy, extract a small shared shell or composite action
  only after the repeated behavior is concrete.
- Put scenario provisioning bodies in `shifter/packer/scripts/<scenario>/`
  where they are covered by Packer lint/SAST/tests. Do not keep long inline
  workflow heredocs as the durable bake implementation.
- Use the existing Packer manifest convention
  `<source>-manifest.json`; update workflow extraction and tests together.
- Preserve the existing Packer source-name selector pattern:
  `packer validate/build -only='*.${{ inputs.ami_type }}'`.
- Reuse `scripts/polaris-aws-range/check_range_health.py` for Polaris evidence
  and the TechVault runbook's container-count/golden-verify contract for
  TechVault. Do not create a second Polaris health model or TechVault scenario
  schema.
- Keep GCP Packer under `shifter/packer/gcp/` separate. GCP image-family
  publication is not the AWS SSM parameter contract.

### Extensibility

The seam is a scenario AMI build profile in Packer:

- `ami_type` / source name controls the logical AMI key and manifest name.
- Scenario artifact location is a validated variable (`polaris` tarball,
  future scenario bundle, or `aptl_version` / lab selector).
- Builder placement and access are variables (`vpc_id`, `subnet_id`,
  no-inbound security group, builder instance profile, root volume size,
  optional KMS key/alias).
- Post-build verification is keyed by AMI type and can grow a future scenario
  verifier without changing the AMI consumer contract.

That seam should allow the next reasonable scenario bake to add one Packer
source, one script directory, one verification profile, and one `ami_type`
choice. It should not require editing the provisioner AMI resolver, adding a
new scenario schema, or introducing a second workflow lifecycle.

### Whole-Repo Surfaces

In scope for implementation design:

- `.github/workflows/packer.yml`
- `.github/workflows/polaris-scenario-bake.yml`
- `.github/workflows/techvault-scenario-bake.yml`
- `.github/workflows/packer-promote.yml` if scenario AMI promotion behavior is
  widened
- `scripts/ami.sh`
- `shifter/packer/*.pkr.hcl`
- `shifter/packer/variables.pkr.hcl`
- `shifter/packer/{dev,proof,prod}.pkrvars.hcl`
- `shifter/packer/scripts/**`
- `shifter/packer/tests/**`
- `scripts/polaris-aws-range/**`
- `docs/ops/techvault-bake-runbook.md`
- `docs/architecture/polaris-scenario-bake-preflight-618.md`
- `docs/architecture/techvault-encrypted-ami-preflight-1455.md`
- `shifter/engine/provisioner/provisioner_ami.py`
- `shifter/engine/provisioner/terraform_vars.py`
- `shifter/engine/provisioner/plans/polaris_range_bootstrap.py`
- `shifter/engine/provisioner/plans/techvault_range_bootstrap.py`
- `platform/terraform/global/iam/github-oidc.tf` if workflow IAM changes
- `platform/terraform/modules/engine-provisioner/iam.tf` as a guardrail to
  preserve, not a place to weaken launch policy
- `.github/quality-path-filters.yaml`, `_quality.yml`, `actionlint`, and ADR
  guard if workflow or guardrail files change

## Gotchas And Anti-Patterns

- Do not merely wrap the existing hand-rolled SSM bake workflow in Packer. The
  point is to let Packer own launch, provision, image creation, and teardown.
- Do not publish an AMI before fresh-instance golden verification. A successful
  Packer provisioner run proves the builder converged; it does not prove the
  image boots into the participant contract.
- Do not lose TechVault's running-stack image semantics. The stack is baked
  running so fresh boot auto-starts containers; range launch must not rerun
  `aptl lab start`.
- Do not lose Polaris's external artifact boundary. The private scenario build
  tarball remains operator-supplied; this public repo must not grow private
  challenge content or CTFd secrets.
- Do not bake per-range credentials, participant passwords, DC private IPs,
  STS credentials, or static Bedrock keys. Those remain runtime setup-plan
  responsibilities.
- Do not add a parallel AMI resolver, scenario DTO, exception hierarchy,
  database model, or persistent AMI inventory for this migration.
- Do not weaken `ec2:Encrypted=true`, per-range security groups, IMDSv2,
  no-inbound bake posture, or the SSM/secret redaction rules to make the bake
  easier.
- Do not leave `packer.yml`, `scripts/ami.sh`, Packer source names, and
  manifests out of sync. The current workflow already lists some choices that
  do not have top-level AWS Packer sources; migration should fix that drift.
- Do not copy GCP `polaris-vm` image-family assumptions into AWS. AWS publishes
  `/shifter/ami/<key>`; GCP publishes image families and optional GDC exports.
- Do not keep the deleted scenario workflows' inline shell as hidden source of
  truth in comments, docs, or helper scripts after migration.

## Non-Goals

- No implementation in this preflight note.
- No redesign of AMI promotion, cross-account sharing, or prod release policy
  unless the follow-up explicitly brings scenario AMIs into that path.
- No change to the scenario `ami_key` schema or the provisioner AMI resolver.
- No range provisioner rewrite and no new setup orchestrator.
- No migration of Polaris or TechVault content into this public repository.
- No new application API, DTO, service, repository, persistence model, logging
  framework, or exception hierarchy.
- No GCP/GDC Packer redesign.
- No weakening of workflow, ADR, Terraform, IAM, or security scanning gates.

## Validation Expectations

For the implementation change, run the repo-required gates for touched
surfaces. At minimum:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd shifter/packer && uv run ruff check . && uv run ruff format --check . && uv run pytest tests/
actionlint
```

Also run `packer validate` for the changed AWS sources, scenario-specific
golden verification in the target AWS environment, and Terraform/IAM checks
when IAM or Terraform files change.

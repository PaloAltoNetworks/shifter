# TechVault Encrypted AMI Preflight (#1455)

Status: pre-implementation guidance

Date: 2026-07-12

Issue: GitHub #1455, "TechVault golden AMI is unencrypted; range provisioner
requires encrypted root volumes"

This requirement-free issue is governed by the GitHub issue. This note records
the architecture boundary and guardrails only; it is not an implementation
plan.

> **Note (#1469, 2026-07-13):** the TechVault bake was migrated to Packer
> (`shifter/packer/techvault.pkr.hcl`, dispatched via
> `.github/workflows/packer.yml` `ami_type=techvault`; the hand-rolled
> `techvault-scenario-bake.yml` is deleted). This note's "replace the bake with
> Packer" non-goal was scoped to #1455; #1469 is the issue that performed that
> migration. The encryption boundary below is unchanged and still binding: the
> bake verifies every EBS mapping is encrypted (`scripts/bake/verify-encrypted-ami.sh`)
> before publishing `/shifter/ami/techvault`, and the provisioner
> `ec2:Encrypted=true` gate is preserved.

## Boundary And Decision

Keep the range provisioner's encrypted-root-volume IAM condition as the
security boundary. The durable fix belongs in the TechVault AMI bake path:
`/shifter/ami/techvault` must point only to an AMI whose root snapshot is
encrypted in the target account and region before the SSM parameter is updated.

Do not make `engine-provisioner` accept unencrypted `RunInstances` volumes. The
current denial is the intended fail-closed behavior when an AMI or account
default would produce an unencrypted root volume.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Provisioner launch policy | `platform/terraform/modules/engine-provisioner/iam.tf` | Preserve the `ec2:RunInstances` split statements, account-owned AMI scope, Range VPC scope, configured-AZ scope, and `ec2:Encrypted=true` volume gate. |
| Runtime AMI indirection | `shifter/engine/provisioner/provisioner_ami.py` and `terraform_vars.py` | Keep `ami_key: techvault` resolving to `/shifter/ami/techvault`; do not commit AMI IDs into scenario YAML, Terraform variables, or app config. |
| TechVault bake workflow | `.github/workflows/techvault-scenario-bake.yml` | Reuse its workflow-dispatch-only, OIDC, input-validation, SSM RunCommand, golden-verify, step-summary, and teardown shape. |
| Manual operator reference | `docs/ops/techvault-bake-runbook.md` | Keep manual and automated bake semantics aligned: running stack, fresh-instance verify, then SSM publication. |
| Account baseline | `scripts/bootstrap/aws_bootstrap.py::_ensure_ebs_encryption_by_default` | Account-level EBS encryption-by-default remains a baseline guard, not the only proof the TechVault AMI is encrypted. |
| Polaris precedent | `docs/architecture/polaris-scenario-bake-preflight-618.md` and `.github/workflows/polaris-scenario-bake.yml` | Reuse the same scenario-bake boundary; do not generalize into a new AMI framework. |
| Workflow and architecture checks | `scripts/adr_guard/adr_guard.py`, `_quality.yml`, `actionlint` | Workflow changes pass ADR guard and actionlint; guardrail weakening needs architecture documentation or a dated exception. |

## Required Cross-Cutting Layers

| Layer | Required treatment |
| --- | --- |
| IAM policy gate | The provisioner task role must continue requiring `ec2:Encrypted=true` for `volume/*` during `RunInstances`. This issue must not widen the policy, add an exception for TechVault, or move encryption enforcement into app code only. |
| AMI creation/publishing gate | The bake must verify the produced AMI's root block device maps to an encrypted snapshot before writing `/shifter/ami/techvault`. SSM publication is success-only after golden verification and encryption verification. |
| KMS boundary | If the bake pins a CMK instead of relying on account-default EBS encryption, use an explicit, non-secret KMS key id/alias parameter or environment-specific constant and ensure the workflow role can use it through EC2/EBS. Do not reuse Secrets Manager, SNS, CloudWatch, or engine-state CMKs casually. |
| GitHub auth surface | Keep `workflow_dispatch`, `permissions: id-token: write, contents: read`, and `aws-actions/configure-aws-credentials`. Do not introduce long-lived AWS keys, PATs, or credentials in workflow inputs. |
| Input validation and shell shape | Continue binding free-form inputs to environment variables and validating them against allowlists before AWS calls. New parameters such as a KMS alias/key id must be validated and passed as data, not interpolated into shell syntax. |
| OS/process exposure | AMI IDs, snapshot IDs, SSM parameter names, KMS aliases, and instance IDs are acceptable diagnostics. Do not print, pass in argv, bake into the image, or include in summaries any AWS secret keys, CTFd tokens, RDP passwords, SSH private keys, or Bedrock static credentials. |
| Runtime bootstrap | `TechVaultRangeBootstrapPlan` remains limited to per-range Bedrock environment setup and verification. It must not repair AMI encryption, copy AMIs, or re-run `aptl lab start`. |
| Error and observability surface | Use GitHub `::error::` annotations and step summaries with non-secret identifiers. Workflow failure should be loud before SSM update if the root snapshot is not encrypted, not a warning after publication. |

## Extensibility Seam

Keep the bake configurable around the encryption target without hard-coding a
single future account shape. The seam is an environment-specific EBS encryption
choice: account default, a validated KMS key alias/id input, or an explicit
checked-in per-environment constant. The AMI verification remains invariant
regardless of that choice.

The same seam should support a future proof/prod bake, a future rotated EBS
CMK, or an encrypted-copy fallback without editing the provisioner IAM policy or
the TechVault scenario contract.

## Whole-Repo Surfaces In Scope

- `.github/workflows/techvault-scenario-bake.yml`
- `docs/ops/techvault-bake-runbook.md`
- `platform/terraform/modules/engine-provisioner/iam.tf`
- `platform/terraform/global/iam/github-oidc.tf` if the bake needs additional
  EC2/KMS permissions
- `scripts/bootstrap/aws_bootstrap.py`
- `shifter/engine/provisioner/provisioner_ami.py`
- `shifter/engine/provisioner/terraform_vars.py`
- `shifter/engine/provisioner/plans/techvault_range_bootstrap.py`
- `shifter/shifter_platform/cms/scenarios/templates/techvault.yaml`
- ADR guard, actionlint, and workflow quality checks when workflow or guardrail
  files change

## Gotchas And Anti-Patterns

- Do not "fix" the launch failure by weakening `ec2:Encrypted=true` or adding a
  TechVault-specific IAM bypass.
- Do not treat `/shifter/ami/techvault` being set as proof of correctness. The
  pointed AMI's root snapshot encryption state is the proof needed before
  publication.
- Do not rely only on the current account's EBS encryption-by-default setting.
  It is a useful baseline, but bake correctness must be verified from the
  actual produced AMI.
- Do not copy the current unencrypted AMI as the durable path unless the
  workflow records that as a temporary fallback and publishes only the encrypted
  copy.
- Do not put KMS key ARNs, AMI IDs, or snapshot IDs into scenario templates.
  Scenario YAML owns the logical `ami_key`, not provider identifiers.
- Do not create a second AMI resolver, scenario schema, or provisioner-side
  encryption repair layer.
- Do not run TechVault stack provisioning at range launch to compensate for an
  unusable bake. Range launch remains boot plus container auto-start plus the
  existing per-range bootstrap.

## Non-Goals

- Changing the range provisioner's IAM trust model or launch policy.
- Replacing the TechVault bake workflow with Packer or a new generic AMI
  framework.
- Promoting TechVault AMIs across accounts.
- Changing Polaris bake behavior except as a precedent to preserve.
- Reworking Bedrock model selection, TechVault runtime bootstrap, RDP access,
  Guacamole, or participant credential storage.
- Adding a formal Ground Control requirement for this requirement-free issue.

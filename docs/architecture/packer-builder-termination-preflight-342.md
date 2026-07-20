# Packer Builder Termination Preflight (#342)

Issue 342 is a requirement-free maintenance fix for AWS Packer AMI builds:
after a Kali AMI bake completed, the transient `packer-builder-kali` EC2
instance was still running. The GitHub issue is the contract.

This note is not an implementation plan. It records the repository-wide
boundaries the implementation must preserve before changing Packer templates or
workflow cleanup.

## Architecture Decisions

- AWS Packer template behavior and the Packer build workflow are the canonical
  lifecycle controls for builder instances. Terraform only consumes the
  published `/shifter/ami/*` SSM parameters and must not learn about transient
  Packer builders.
- Linux AWS builders (`kali`, `ubuntu`, `brokenbk`) should fail closed toward
  termination. Their `amazon-ebs` sources use `shutdown_behavior = "terminate"`
  and must not grow a `skip_create_ami` path for normal builds.
- Windows AWS builders (`windows`, `dc`) are the intentional exception:
  `shutdown_behavior = "stop"` plus `disable_stop_instance = true` is required
  for sysprep so Packer can create the AMI from the stopped instance. Do not
  make the Linux rule mechanically apply to Windows/DC.
- `.github/workflows/packer.yml` is the defense-in-depth cleanup layer. It can
  terminate leftover builders after a failed or successful workflow, but SSM
  publication must remain success-only and tied to the manifest from the same
  successful Packer build.
- Builder cleanup must select instances by controlled builder identity tags.
  Today that identity is the `run_tags.Name = packer-builder-<ami_type>`
  convention in each AWS template. If cleanup becomes stricter, add the new
  selector as Packer `run_tags` on every AWS source and test it there; do not
  maintain a second ad hoc source-name map only in the workflow shell.
- GCP Packer templates under `shifter/packer/gcp/` are a separate provider
  surface. Do not copy AWS SSM, EC2 shutdown, or `amazon-ebs` cleanup semantics
  into the GCP image-family flow.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| AWS builder templates | `shifter/packer/{kali,ubuntu,brokenbk,windows,dc}.pkr.hcl` | Keep lifecycle tags, `shutdown_behavior`, manifest names, and source names together. |
| Packer variable contract | `shifter/packer/variables.pkr.hcl` and `*.pkrvars.hcl` | Preserve required variables with no silent defaults; do not put secrets in var files or `-var` command lines. |
| Packer workflow | `.github/workflows/packer.yml` | Reuse the existing validate, build, manifest extraction, SSM update, upload, and `always()` cleanup sequence. |
| AMI consumers | `platform/terraform/environments/{dev,proof,prod}/portal/main.tf` | Keep `/shifter/ami/{kali,ubuntu,windows,dc}` as the stable consumption contract. |
| IAM surface | `platform/terraform/global/iam/github-oidc.tf` | Reuse the consolidated GitHub OIDC compute policy; do not add another managed policy attachment for cleanup. |
| Packer tests | `shifter/packer/tests/test_packer.py` and `test_packer_gcp.py` | Encode lifecycle/tag/provider separation so future AMI types cannot regress cleanup behavior silently. |
| Workflow validation | `actionlint`, `.github/quality-path-filters.yaml`, `_quality.yml` | Workflow edits must pass actionlint and trigger the quality path. |
| Architecture guardrails | `python3 scripts/adr_guard/adr_guard.py --all --level ci` | Required before completion when workflow or guardrail files are touched. |
| Release notes | `changelog.d/<issue>.fixed.md` | A workflow/Packer behavior fix should leave a fragment; do not edit `CHANGELOG.md` directly. |

## Security Layers

- Dispatch/auth surface: the privileged build runs on a self-hosted GitHub
  Actions runner and assumes AWS roles through OIDC via
  `aws-actions/configure-aws-credentials`. Do not add static AWS credentials,
  long-lived access keys, or a second privileged dispatch path.
- Input shape: `ami_type` and `environment` are workflow choice inputs. Any new
  input that reaches shell, Packer, AWS CLI filters, SSM names, or tag values
  must be a choice input or validated against a tight allowlist before use. If
  the free-form `ref` input is changed while touching this workflow, prefer a
  protected-branch choice because this workflow assumes deploy credentials.
- Packer config shape: `packer validate -var-file=<env>.pkrvars.hcl
  -only='*.<ami_type>' .` is the structural gate. The implementation must keep
  source names, manifest names, and workflow `-only` selectors aligned.
- AWS resource-selection policy: cleanup may terminate EC2 instances, so its
  filters must be derived from Packer `run_tags`, constrained to the configured
  AWS region, and scoped to builder lifecycle states only. Do not broaden cleanup
  to generic `Project=shifter`, AMI tags, or age-only matching.
- Secret-handling surface: AWS role ARNs stay in GitHub secrets; var files stay
  non-secret infrastructure config; summaries may show AMI IDs and SSM parameter
  names but must not print role ARNs, session credentials, private keys, or
  generated Windows passwords.
- OS/process exposure: do not pass secrets via process argv, Packer `-var`, or
  shell-expanded workflow inputs. Use environment binding for any non-secret
  dynamic values, quote all shell references, and keep generated manifests as CI
  artifacts rather than source edits.
- Error/report envelope: workflow failures should use GitHub `::error::` and
  step summaries without leaking credential material. Cleanup failure must remain
  visible; do not hide it behind `|| true` if orphaned compute cost is the bug.
  Conversely, cleanup must not make a failed bake publish an AMI or update SSM.
- Repository validators: `.github/workflows/**` edits must pass `actionlint` and
  ADR guard. Terraform IAM edits must also respect the GitHub OIDC attachment
  cap and policy-size checks in `scripts/check_tf_iam_role_naming/`.

## Extensibility Seam

The seam is builder lifecycle metadata, not a new inventory system. The next
reasonable changes are adding a new AWS AMI type, making cleanup per-run instead
of per-AMI-type, or building outside `us-east-2`. Those should be represented by
validated workflow inputs and Packer `run_tags` shared by every AWS source. A
future per-run selector belongs in builder tags such as a workflow run id or
build id; it should not be inferred from AMI names, manifests, timestamps, or
Terraform state.

## Gotchas And Anti-Patterns

- Do not make the fix Kali-only. The failing instance was Kali, but the policy
  must cover all AWS `amazon-ebs` sources that can leave builders behind.
- Do not apply Linux `shutdown_behavior = "terminate"` to Windows/DC sysprep
  builders.
- Do not set or introduce `skip_create_ami = true` for the normal workflow path.
  That changes the product outcome rather than fixing cleanup.
- Do not update `/shifter/ami/<type>` unless the manifest was produced by the
  successful build in the same run.
- Do not terminate by a loose name, project tag, or old timestamp alone. That can
  kill an unrelated manual build or a concurrent workflow for the same AMI type.
- Do not move AMI publication into Terraform, the engine provisioner, or
  platform runtime code. They consume AMI IDs; they do not own Packer builders.
- Do not copy GCP image-family logic into AWS SSM publication, or AWS EC2 cleanup
  into the GCP Packer workflow.
- Do not add a duplicate validation script if the invariant can live in
  `shifter/packer/tests/test_packer.py` or an existing workflow validator.

## Non-Goals

- No redesign of AMI promotion, cross-account sharing, or prod SSM update flow.
- No new AMI family, base image, provisioning script, package set, or guest
  runtime behavior.
- No Terraform range, portal, engine provisioner, or Django application changes
  except if IAM policy scope is intentionally tightened for the existing
  workflow role.
- No cleanup of unrelated historical AWS resources beyond builders that match
  the controlled Packer cleanup selector.
- No new exception hierarchy, schema package, service facade, database state, or
  persistent inventory for Packer builder instances.

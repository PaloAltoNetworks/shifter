# Packer Base-Build Privilege Boundary Preflight (#1656)

Status: pre-implementation guidance

Date: 2026-07-15

Issue #1656 is the shipping contract. This is a requirement-free run. This
note does not change a workflow, IAM policy, GitHub setting, AMI, or SSM
parameter.

## Decision Boundary

This hardening stays in the existing AWS image workflow, global IAM Terraform,
bootstrap, operator-helper, and repository guardrail surfaces. It does not add
an image registry, deployment framework, application schema, database model,
service/repository layer, exception hierarchy, or logging framework.

The first issue item is already present on `dev`: the base-image verification
gate reads `PACKER_VERIFY_*_<ENV>` repository Actions variables and validates
them before use. Preserve that contract. The unresolved boundaries are:

1. the provenance and shape of the pre-promoted DC identifier published to
   `/shifter/ami/dc`; and
2. the AWS principal and OIDC subject allowed to run a privileged base build
   and pass the range instance role to EC2.

ADR-003 and ADR-004 already own workflow routing and policy enforcement. A new
top-level ADR is not needed. If implementation adds a repo-native invariant,
record it as a new ADR-004 rule and wire the same checker into pre-commit and
CI; do not leave a test-only or prose-only guardrail.

## Architecture Decisions And Guardrails

- Keep verification placement in trusted Actions configuration. Subnet IDs,
  security-group IDs, and instance-profile names are identifiers, not secrets,
  so repository or environment variables are appropriate. They must not return
  as `workflow_dispatch` inputs. Continue resolving the selected environment
  through an explicit `dev`/`proof` case with required-value and identifier
  checks before AWS CLI use.
- Treat `shifter/packer/dc-amis.json` as the only DC registry and
  `/shifter/ami/dc` as the only runtime pointer. Both publishers
  (`packer.yml` and `packer-promote.yml`) must read the registry from one
  explicit protected provenance ref, independent of a caller-supplied checkout
  ref or a mutable self-hosted-runner workspace. The current operational flow
  makes protected `dev` the canonical registry source for dev/proof seeding and
  prod promotion. A different source may be adopted only as another explicit,
  protected policy value, never as free-form dispatch input.
- Use a separate checkout directory (or equivalently immutable fetched blob)
  for trusted DC provenance, with the SHA/ref recorded and Git credentials not
  persisted. Do not overwrite the build checkout and do not rely on whichever
  `dc-amis.json` happens to exist under the job's default working directory.
- Resolve the environment key with `jq -e`, require exactly one non-empty string
  matching the AWS AMI identifier shape, and verify with EC2 that the AMI is
  visible, `available`, and owned by the expected account before SSM mutation.
  The prod publisher needs the same validation; its current bare `jq -r
  '.prod'` is not an acceptable second schema. Keep one resolver/validator
  contract shared by the two publisher call sites, sourced from protected
  code, rather than two drifting inline implementations.
- The base `build` job must not continue using the general Terraform deploy
  principal as its effective AWS privilege boundary. That role legitimately
  passes portal EC2, ECS, Lambda, logging, Firehose, RDS, Bedrock, Scheduler,
  and range roles, so it cannot simultaneously prove that a base verification
  instance may receive only the range role. An inline session policy in the
  workflow is useful defense in depth but is still workflow-controlled and is
  not a substitute for an IAM principal boundary.
- Define the least-privilege base-image principal in the existing
  `platform/terraform/global/iam` stack; do not create another Terraform root or
  static AWS credentials. Its `iam:PassRole` resource must be the exact
  environment range role (`shifter-${environment}-range-range-instance`), with
  `iam:PassedToService = ec2.amazonaws.com`. Do not use `shifter-*`,
  `*-range-instance`, profile-name validation, role tags, or a permissions
  boundary alone as the authorization resource scope. AWS explicitly warns
  that role tags are not a `PassRole` authorization boundary.
- Give that principal only the EC2/SSM/image-publication operations exercised
  by the base Packer sources, fresh-boot verifier, cleanup, and the allowed
  `/shifter/ami/<base-type>` parameters. It receives no IAM mutation, Secrets
  Manager, arbitrary Parameter Store, scenario artifact-bucket, or scenario
  builder-profile capability. `bake-scenario` keeps its distinct input and
  permission contract; do not widen the base principal to make both jobs look
  uniform.
- Scope the base principal's OIDC trust to `aud = sts.amazonaws.com` and the
  repository's effective exact protected subject(s), not `repo:...:*`. Verify
  the repository's live subject format before rollout: GitHub subjects differ
  for branch jobs and jobs that reference an Environment, and repositories may
  use immutable owner/repository IDs or a customized subject. Do not copy a
  guessed subject string into IAM.
- If the shared deploy role's `repo:...:*` trust is tightened in the same
  change, inventory every caller first. Jobs with `environment:` emit an
  `environment:<name>` subject instead of a branch subject. Those subjects are
  safe only when the corresponding GitHub Environment has protected deployment
  branch rules. Do not remove wildcard trust by replacing it with branch-only
  subjects and break `_core.yml`, `_range.yml`, `_shifter-engine.yml`, or
  `_shifter-platform.yml`; do not preserve wildcard trust merely to avoid that
  inventory.
- Keep the workflow's pre-authentication `dev|main` check as readable defense
  in depth, but align all dispatchers with it. `scripts/ami.sh` currently sends
  the current branch as the workflow ref, and MCP `build_ami` accepts/defaults
  to a working-tree branch. A feature-branch copy can alter the workflow before
  the inline check executes. Operator helpers must select an allowed protected
  workflow ref and must not advertise a bypass that IAM will reject.
- Preserve least workflow permissions (`contents: read`, `id-token: write` only
  on credentialed jobs), SHA-pinned actions, self-hosted-runner restrictions,
  `set -euo pipefail`, success-only SSM publication, and `always()` cleanup.
  Use a run-scoped role session name so CloudTrail can correlate AWS calls to
  `github.run_id`/attempt without exposing credentials.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Base AMI orchestration | `.github/workflows/packer.yml` | Keep the existing ref gate, Packer validation/build, manifest extraction, fresh-boot validation, success-only publish, summary, artifact, and cleanup sequence. Do not add another base-build workflow. |
| DC publication | `.github/workflows/packer.yml`, `.github/workflows/packer-promote.yml`, `shifter/packer/dc-amis.json` | Keep pre-promoted DC semantics and make both publishers consume the same protected-provenance resolver/validator contract. Never publish `dc.pkr.hcl` as `/shifter/ami/dc`. |
| Verification config | `PACKER_VERIFY_*_<ENV>` bindings in `packer.yml`; `docs/dev/aws-ami-seeding-runbook.md` | Preserve trusted admin configuration, explicit environment mapping, fail-closed presence checks, and identifier validation. |
| Fresh-boot validation | `shifter/packer/scripts/bake/base-image-verify.sh` | Reuse IMDSv2, no-inbound SSM checks, bounded polling, reboot proof, and trap cleanup. Do not duplicate guest validation in IAM or Terraform code. |
| Range identity | `platform/terraform/modules/range/vpc/iam.tf` and the environment range outputs | Authorize the exact Terraform-owned range role/profile. Do not create a lookalike validation role or grant range guests new SSM Parameter Store access. |
| OIDC/IAM ownership | `platform/terraform/global/iam/github-oidc.tf` | Add the image principal and policy beside the existing deploy identity, retaining `jsonencode`, account/environment derivation, policy-size awareness, boundaries, tags, and outputs. No parallel IAM module or policy generator. |
| Bootstrap/secret wiring | `scripts/bootstrap/aws_bootstrap.py`, `scripts/bootstrap/deploy.py`, `docs/dev/deploy-secrets.md` | Extend the existing global-IAM apply/output and GitHub secret/variable conventions if another role ARN is required. Do not require operators to hand-create an untracked IAM role. |
| IAM guardrails | `scripts/check_tf_iam_role_naming/`, `.pre-commit-config.yaml`, `_quality.yml`, `docs/adr/index.yaml` | Extend the existing OIDC/IAM checker family to pin exact-subject and exact-range-role invariants, with positive and negative tests and local/CI parity. |
| Workflow tests | `shifter/packer/tests/test_packer.py` | Keep structural/behavioral tests close to Packer; cover both DC publishers, trusted checkout provenance, absence of verify dispatch inputs, ordering before SSM publish, and failure on invalid/missing AMI data. |
| Operator dispatch | `scripts/ami.sh`, `mcp/ops` `build_ami`/`promote_ami` | Keep one protected-ref policy aligned with workflow and IAM. Preserve argv-based execution and token-in-environment handling; never interpolate a token or ref into shell source. |
| Durable state | `/shifter/ami/*` SSM parameters and Packer manifests | Keep SSM as the runtime pointer and manifests as build evidence. No database, Redis, new parameter namespace, or second DC registry. |

## Cross-Cutting Layers The Intended Design Must Pass

1. **Dispatch/auth shape.** `ami_type` and `environment` remain choice inputs;
   verification placement and the trusted DC ref are not dispatcher-selected.
   Every local/MCP dispatcher uses the same protected workflow-ref policy.
2. **GitHub authorization.** The workflow file executed for a credentialed job
   comes from a permitted protected subject. Environment-bearing callers are
   matched to their actual environment subjects and protected deployment
   rules; branch-bearing callers are matched to exact protected branch
   subjects. Pull-request and feature-branch subjects receive no AWS role.
3. **OIDC/STS.** The pinned credentials action requests a short-lived token
   with exact audience/subject trust and a run-correlatable session name. No
   access key, PAT, static session token, or caller-controlled role ARN is
   introduced.
4. **IAM policy gate.** The base principal can pass exactly the range role to
   EC2 and no other role. Its allowed AWS verbs and SSM parameter resources are
   base-pipeline-specific. The CI permissions boundary remains a ceiling, not a
   replacement for a narrow identity policy.
5. **Configuration shape.** Explicit environment mapping selects the trusted
   subnet, security group, profile, role ARN, and SSM namespace. Existing
   `req`/`match` checks remain fail-closed. `jq -e`, AMI syntax validation, and
   EC2 ownership/state validation protect the DC artifact shape before publish.
6. **Secret handling.** Network IDs, AMI IDs, profile names, refs, and SHAs may
   be bounded diagnostics; AWS credentials, GitHub tokens, role ARNs containing
   account IDs, tfvars, domain credentials, and complete environments may not
   enter argv, summaries, artifacts, or logs. Repository variables do not
   become secrets merely by moving them to the secrets store.
7. **OS/process exposure.** AWS credentials stay in the action/provider
   environment, never command arguments. AWS CLI argv contains only validated
   non-secret identifiers. Protected checkout credentials are not persisted in
   the self-hosted runner's Git config, and cleanup remains safe on cancellation
   or partial failure.
8. **Error and observability envelope.** Failures use existing `::error::`
   annotations and identify the missing field, environment, validation phase,
   and run correlation without echoing the rejected value or dumping policy,
   environment, cloud-init, SSM output, or credentials. Step summaries record
   AMI ID, trusted provenance ref/SHA, target environment, validation result,
   and SSM path. CloudTrail supplies the authoritative AWS audit trail.
9. **Persistence/publication.** No write to `/shifter/ami/*` occurs until
   provenance, shape, AWS visibility/ownership/state, and applicable boot checks
   pass. A failure leaves the previous pointer intact; no rollback registry or
   compensating database state is added.
10. **Repository enforcement.** `actionlint`, Packer tests, Terraform
    fmt/validate/TFLint/Checkov, the IAM checker, bootstrap tests, and ADR guard
    all see the change. A new rule is documented in ADR-004 and runs identically
    in pre-commit and `_quality.yml`.

## Extensibility Seam

The seam is one environment-keyed, Terraform-owned image-pipeline identity and
trusted configuration binding. Adding a future AWS environment should require
one environment entry that supplies its role output, verify network/profile
configuration, exact allowed range-role ARN, OIDC subject policy, and SSM
namespace. It must not require another workflow, copied IAM policy schema,
another DC registry, or dynamic evaluation of a variable name.

Image capabilities stay explicit. A future base AMI opts into the existing
base principal, SSM path allowlist, and verifier profile; a scenario AMI does
not inherit those permissions merely because both use Packer.

## Gotchas And Anti-Patterns

- Do not treat `inputs.ref` validation as a trust boundary: the workflow version
  containing that validation may itself come from the dispatched ref.
- Do not assume `github.sha`, `github.ref`, the checkout ref, and the OIDC
  `sub` are interchangeable. Record and test each intended value.
- Do not hardcode the legacy `repo:ORG/REPO:...` subject without checking
  whether immutable IDs or custom claims are active for this repository.
- Do not apply a branch subject to an `environment:` job; GitHub replaces that
  subject suffix with `environment:<name>`.
- Do not keep the broad deploy role for convenience and call an inline session
  policy an independent IAM boundary. The workflow can edit or omit it.
- Do not authorize `PassRole` by suffix, `shifter-*`, tags, or
  `iam:PassedToService` alone. The role resource and destination service are
  complementary constraints.
- Do not scope the shared deploy role's EC2 `PassRole` to only range guests
  without inventorying portal/runner/NGFW launch profiles; that would break
  Terraform while leaving the Packer boundary conceptually confused.
- Do not conflate an instance profile name with its contained role ARN. EC2 is
  given the profile, while IAM authorizes passing the role; validate and bind
  both to the same Terraform-owned identity.
- Do not read trusted provenance through the untrusted build checkout, runner
  leftovers, a caller URL, or a mutable artifact without digest/commit binding.
- Do not validate only AMI syntax. A well-formed ID can be missing, unavailable,
  shared from the wrong account, or point at the wrong lifecycle artifact.
- Do not fix only `packer.yml`; `packer-promote.yml` also publishes
  `/shifter/ami/dc`, and `scripts/ami.sh` plus MCP expose workflow-ref choices.
- Do not duplicate DC JSON parsing, environment mapping, or error messages
  across workflows. Keep one protected resolver contract and thin call sites.
- Do not print repository variables wholesale, enable shell tracing, emit AWS
  credential action outputs, upload runner workspaces, or include account IDs in
  committed examples.
- Do not weaken Checkov, actionlint, ADR guard, policy-size limits, or protected
  GitHub Environment rules to make the IAM rollout pass.

## Non-Goals And Implementation Boundaries

- No guest DNS, Packer provisioner, scenario content, AMI rebuild, or live SSM
  mutation in this issue.
- No change to the pre-promoted `internal.shifter` DC lifecycle, password
  coordination, generalized `dc.pkr.hcl`, or runtime provisioner AMI lookup.
- No new API, DTO, model, migration, service, repository, cache, exception
  hierarchy, error schema, or cloud-provider abstraction.
- No redesign of GCP image build/promotion, portal/runtime IAM, range guest
  permissions, GitHub runner networking, Cognito/OIDC application auth, or
  Terraform state layout.
- No permissions expansion for scenario bakes under cover of base-build
  hardening. Scenario profile selection is a separate boundary and should be
  split if it cannot meet its own least-privilege contract.
- No automatic merge, deployment, IAM apply, GitHub Environment mutation, AMI
  publication, or production promotion as part of the implementation PR.

## Validation Expectations

At minimum, implementation must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
actionlint
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run the Packer test suite, the IAM checker tests, bootstrap and MCP tests
when their surfaces change, Terraform fmt/validate and reviewed plans for every
affected global-IAM environment, and Checkov through its canonical local/CI
configuration. Negative tests must prove that a feature-branch OIDC subject, an
environment-mismatched subject, a non-range role, a wildcard `PassRole`, a
checked-out-ref DC registry, malformed/missing DC data, and a non-owned or
unavailable AMI all fail closed.

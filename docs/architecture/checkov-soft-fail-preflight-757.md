# Checkov Soft-Fail Policy (ADR-004-R11)

Status: implemented

Original tracking issue: <https://github.com/Brad-Edwards/shifter/issues/757>

Migrated from: <https://github.com/PaloAltoNetworks/shifter/issues/1192>

## Posture

Checkov is a **blocking gate** for first-party Terraform under
`platform/terraform/`. There is no Terraform soft-fail.

The pre-commit hook
(`.pre-commit-config.yaml` `checkov`) and the GitHub Actions
`security-iac` job (`.github/workflows/_quality.yml`) both consume the same
configuration file at `platform/terraform/.checkov.yaml`, so there is one
canonical policy boundary instead of two diverging copies.

Kubernetes Checkov (`security-k8s`) is a separate policy surface and stays
soft-fail / `continue-on-error` while manifest hardening proceeds under a
separate issue. Terraform soft-fail is NOT allowed to inherit from the
Kubernetes posture.

## Waiver process

When a Checkov check fires on a finding that is genuinely wrong to "fix":

1. Add the rule to `platform/terraform/.checkov.yaml` `skip-check:` (for
   repo-wide rule waivers), OR add an inline
   `# checkov:skip=CKV_X:reason. See ADR-004-R11 exception <slug>.`
   comment immediately inside the resource block (for per-resource
   waivers).
2. Add a matching entry to `docs/adr/exceptions.yaml` with:
   - `rule_id: ADR-004-R11`
   - `owner` — @-handle of the engineer who owns the exception
   - `reason` — must include the Checkov policy ID
   - `expires_on` — ISO 8601 date (`adr_guard.py` rejects expired entries)
   - `paths` — optional repo-relative list of files/directories in scope

Expiration forces owner re-review.

`adr_guard.py` is the structural gate that validates the exception
schema. The `Quality / Security (IaC)` workflow job is the structural
gate that runs Checkov against the same config in CI.

## Implementation summary

Issue [#757](https://github.com/Brad-Edwards/shifter/issues/757) reduced
the baseline of 321 first-party Terraform Checkov findings to zero
unwaived. The work split as follows:

- **141 fixes** — Security group descriptions, EC2 detailed
  monitoring / EBS-optimized / IMDSv2 / root-device encryption,
  CloudWatch log retention bumped to 365 days, RDS Postgres force_ssl /
  enhanced monitoring / Performance Insights CMK / query logging /
  copy-tags-to-snapshot, KMS-CMK encryption for CloudWatch log groups,
  SQS queues, SNS topics, Kinesis Firehose, ECR repositories, Network
  Firewall (rule groups, firewall policy, firewall itself), Secrets
  Manager secrets (env, demo, NGFW), DynamoDB engine-state locks,
  EventBridge Scheduler, GKE node-pool auto_repair / auto_upgrade /
  workload_metadata_config, Artifact Registry CMEK.
- **15 path-scoped principled exceptions** — Cognito pre-signup
  synchronous Lambda hardening checks, Redis encryption (consumer-side
  follow-up #295), Guacd ECS read-only root (tmpfs follow-up), demo
  workshop instance public IPs / open ingress, NGFW EIP runtime
  association, log-archive S3 bucket access-logging recursion /
  versioning / cross-region replication, service-account IAM user
  policies, engine-provisioner wildcard IAM by AWS-API design.
- **3 repo-wide rule waivers** — SSM Parameter SecureString (repo
  policy is secrets-in-Secrets-Manager), ECR mutable tags (deploy
  pattern), Lambda `templatefile` false-positive on hard-coded secret.

Every waiver maps 1:1 to a `docs/adr/exceptions.yaml` entry with owner,
reason, expiry, and affected paths.

## Anti-patterns

- Do not add a Checkov `skip-check` or inline `# checkov:skip=…` without
  a matching `docs/adr/exceptions.yaml` entry. The ADR registry is the
  audit trail; an inline skip without it is the failure mode this rule
  prevents.
- Do not move accepted Terraform IaC risk into `# nosec` /
  `tfsec:ignore` comments or into hidden config; the waiver must live in
  the ADR registry.
- Do not reuse a waiver entry for an unrelated rule. One Checkov check
  ID per inline skip; one ADR entry covers a coherent set of related
  IDs.
- Do not pass live cloud credentials, rendered tfvars, or Terraform
  state through Checkov command arguments; static scanning only.
- Do not re-introduce `--soft-fail` on the Terraform path to make a
  finding disappear. Either fix the finding or file the waiver.

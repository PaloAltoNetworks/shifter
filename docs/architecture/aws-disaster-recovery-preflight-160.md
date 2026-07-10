# AWS Disaster Recovery Preflight (#160)

Status: pre-implementation guidance

Date: 2026-06-24

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/160>

## Scope Boundary

Issue #160 asks for disaster recovery procedures for the AWS portal stack:
RDS/PostgreSQL, the portal upload S3 bucket, EC2 portal/AgentChat runtime,
Cognito, Terraform state, recovery targets, one tested recovery exercise, and
backup-failure alerting.

This note is not the DR runbook and not an implementation plan. It constrains
the later implementation so DR posture is designed against the whole repo
rather than as a local checklist.

The DR work must keep these concepts separate:

1. Availability controls: Multi-AZ, ASG replacement, health checks, lifecycle
   hooks, and service-managed HA.
2. Recoverability controls: backups, snapshots, exported identity data, state
   object versions, and restore commands.
3. Evidence: dated restore-test output, RTO/RPO observations, and alarm-test
   proof.
4. Data classification: durable application state, ephemeral upload objects,
   generated compute, identity-provider state, Terraform state, and logs.

## Architecture Decisions

- Treat the GitHub issue as the shipping contract. No Ground Control
  requirement is attached.
- Keep DR documentation operational and provider-specific for this issue. The
  requested components are AWS components (RDS, S3, EC2, Cognito, S3-backed
  Terraform state); do not redesign GCP, Kubernetes, Helm, or backend-bundle
  selection to satisfy this issue.
- RDS is the authoritative application data store. Its DR posture belongs in
  `platform/terraform/modules/portal/rds/`, the portal environment roots, and
  the runbook. The implementation must align backup retention, deletion
  protection, final snapshots, Multi-AZ, log exports, PITR restore testing, and
  restore evidence instead of adding a second persistence abstraction.
- The portal user-uploads S3 bucket remains classified as ephemeral unless a
  separate design decision changes that classification. The current
  `docs/architecture/s3-bucket-hardening-preflight.md` decision rejects
  versioning/CRR for this bucket because authoritative state lives in RDS.
  DR work must not silently flip that posture to make a generic checklist pass.
- EC2 portal/AgentChat instances are generated runtime. Recovery should rebuild
  from Terraform, ECR image tags/digests, SSM parameters, launch templates, and
  ASG instance refresh. AMI backup work is only justified for prebaked or
  irreplaceable images; do not back up disposable root volumes as application
  state.
- Cognito is an external identity state holder. User pool configuration is
  Terraform-managed; user identities, MFA enrollment, groups, and hosted-UI
  state are not in RDS. The runbook must distinguish Cognito export/reseed
  limits from Django `auth_user`/`management.UserProfile` restore through RDS.
- Terraform state recovery belongs at the existing bootstrap/backend seam:
  `scripts/bootstrap/terraform_backend.py`,
  `scripts/terraform/render_aws_backend_configs.py`, S3 backend configs, and
  the bootstrap-created state bucket. Do not commit live backend names, copy
  state through ad hoc repo files, or confuse state with plan artifacts/tfvars.
- Backup/restore monitoring should reuse existing CloudWatch/SNS alarm
  conventions and the per-environment `aws_sns_topic.alerts` routing where the
  portal root already owns it. Do not add a parallel alarm DSL or a bespoke
  notification path.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #160 |
| --- | --- | --- |
| RDS ownership | `platform/terraform/modules/portal/rds/`, env roots under `platform/terraform/environments/*/portal/` | Extend retention, restore-test support, or backup alarms here. Preserve storage encryption, SG-only ingress, deletion protection, final snapshot, and log-export patterns. |
| Guacamole RDS adjacency | `platform/terraform/modules/guacamole/rds.tf`, env `guacamole_db_*` variables | If the runbook mentions portal DB recovery, call out Guacamole DB separately; do not assume the portal RDS settings cover it. |
| Portal upload bucket | `platform/terraform/modules/portal/s3/`, `docs/architecture/s3-bucket-hardening-preflight.md` | Preserve the ephemeral classification unless the implementation explicitly changes the data class and updates ADR exceptions/checkov skips. |
| Runtime storage adapter | `shared.cloud.get_object_storage()`, `shared.cloud.aws.storage`, `cms.assets.s3`, `ctf.s3` | Runtime verification or cleanup must reuse the object-storage protocol and sanitizers, not raw boto3 logic scattered through domain services. The legacy experiment storage adapter was removed by ADR-027. |
| Upload validation | `shared.uploads.inspection`, upload-token flows, `sanitize_s3_filename` | Restore validation must not bypass existing key, content, quota, token, or server-side inspection contracts. |
| EC2/ASG runtime | `platform/terraform/modules/portal/ec2/`, `user_data.sh`, `scripts/portal-deploy/deploy_portal.sh`, `_shifter-platform.yml` | Recreate portal capacity through launch templates, ASG refresh, SSM parameter hydration, ECR image refs, and worker-health supervision. Keep first boot and SSM redeploy paths consistent. |
| Cognito/OIDC | `platform/terraform/modules/portal/cognito/`, `config._oidc_settings`, `config.oidc`, `config.cognito_groups`, `management.UserProfile` | Keep identity-provider export/reseed distinct from Django user/profile/audit restoration. Do not create a second user schema. |
| Secrets/config binding | Secrets Manager, `platform/terraform/modules/portal/ssm/`, `entrypoint.sh`, `config._runtime_env`, `config._cloud` | SSM carries non-secret config and secret references; secret values stay in Secrets Manager/provider stores and are hydrated by existing runtime paths. |
| Terraform state | S3 backend blocks, `scripts/bootstrap/terraform_backend.py`, `scripts/terraform/render_aws_backend_configs.py`, `docs/dev/deploy-secrets.md` | State backup/copy guidance belongs in bootstrap/backend docs and scripts. Generated backend configs stay outside the product repo or in CI temp space. |
| Alarm conventions | `portal/messaging`, `portal/redis`, `portal/ec2/observability.tf`, `engine-provisioner/alarms.tf`, `log-aggregation/alarms.tf` | New backup/restore alarms should match period/evaluation/action/tag shapes and route through existing SNS topics where possible. |
| Logging and responses | `config.logging.ECSFormatter`, `shared.log_sanitize`, `shared.errors` | Operator logs must be sanitized and low-cardinality. No raw export bodies, secrets, signed URLs, or full provider exceptions in user-facing responses. |
| Enforcement | `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `.tflint.hcl`, `actionlint`, `.importlinter`, ADR exception registry | Terraform, workflow, guardrail, and platform changes must pass the repo-native checks and keep ADR exceptions synchronized. |

## Cross-Cutting Layers

- Auth surface: no new public application endpoint is needed for DR. Operator
  procedures should use existing AWS IAM/GitHub OIDC roles and AWS console/CLI
  authorization. If any app-facing status is added later, it must be
  authenticated/admin-only and must not expose backup contents, user exports,
  state paths, bucket names, ARNs, or raw provider errors.
- Secret-handling surface: DB credentials, app secrets, Cognito client secret,
  Redis AUTH, Guacamole secrets, DC password, and field-encryption key stay in
  Secrets Manager/provider secret stores. DR scripts or runbook commands must
  not print secret values, write them to tracked files, pass them through
  process argv, upload them as CI artifacts, or embed them in Terraform outputs.
  Terraform state may contain generated secret material; do not claim state is
  secret-free.
- Env-binding shape: environment-owned values continue through
  `terraform.tfvars` baselines plus gitignored `local.auto.tfvars` or GitHub
  Actions secret payloads, then through Terraform variables, SSM parameters,
  and existing runtime env parsers. Do not add a second YAML/JSON schema for DR
  targets when a runbook matrix is sufficient.
- Config validators: Terraform variable validation/preconditions, provider
  validation, Checkov skips plus `docs/adr/exceptions.yaml`, TFLint, ADR guard,
  actionlint, and import-linter all remain active. If backup retention,
  replication, or final-snapshot posture changes, validate impossible
  combinations in Terraform rather than in prose only.
- OS/process exposure: AWS CLI, `terraform`, and helper scripts must use argv
  arrays or existing redaction helpers where scripts already provide them.
  Avoid `-var secret=...`, shell traces, `echo` diagnostics for tfvars/export
  bodies, Cognito user exports in world-readable temp files, and Docker env
  output. Diagnostics should name component, environment, command class, and
  docs path without echoing sensitive payloads.
- Error-envelope surface: DR failures are operator-facing unless a later issue
  creates an app API. Keep failure messages coarse and authored. Use
  `classify_user_message`/`safe_user_message` for any HTTP exposure and
  `logger.exception` plus sanitized fields for logs.
- Logging/observability surface: use ECS JSON logging in app code and
  CloudWatch/EventBridge/SNS in Terraform. Metrics and event rules should have
  low-cardinality dimensions such as component, environment/name prefix, and
  resource class. Do not label metrics with S3 keys, object names, Cognito
  emails, user pool exports, DB endpoints, ARNs, queue URLs, image tags, or
  Terraform state object keys.

## Extensibility Seam

The durable seam is a component recovery matrix in the DR runbook:

- component: RDS, portal uploads, portal EC2/ASG, Cognito, Terraform state,
  Guacamole RDS if included;
- data class: authoritative, ephemeral, generated, identity-provider managed,
  infrastructure state;
- owner surface: Terraform module/root, script, or external service;
- target: RTO and RPO in explicit units;
- restore primitive: PITR/snapshot restore, object re-upload/reconciliation,
  ASG rebuild, Cognito export/reseed, state object version restore;
- evidence: last tested date, operator, command/artifact location, result;
- alert source: CloudWatch alarm/EventBridge rule/AWS Backup event/RDS event
  subscription and SNS topic;
- region policy: same-region only, cross-AZ, cross-region copy, or not
  applicable.

This matrix lets future GCP or multi-region DR add rows/columns without
rewriting application services. Terraform parameters should be added only where
the target drives actual infrastructure behavior, such as backup retention,
destination region, replication role/KMS, alarm enablement, or test cadence.

## Gotchas

- Multi-AZ is availability, not a tested restore. It can improve RTO but does
  not replace PITR evidence or final-snapshot recovery.
- Backup retention is not RPO by itself. The RPO must account for RDS PITR
  granularity, last restorable time, export cadence, S3 object classification,
  and Terraform state object versioning.
- The portal upload bucket has multiple runtime consumers (agent uploads,
  experiment scripts, CTF attachments). Reclassifying it as durable affects all
  of them and requires revisiting lifecycle, versioning, CRR, KMS, delete
  semantics, and ADR exceptions.
- S3 CRR requires versioning. Enabling it on portal uploads changes deletion
  and retention semantics and can retain data users expected to delete.
- Cognito exports can contain PII and may not fully recreate MFA/session state.
  The app's Django users/profiles/groups are restored from RDS and are only
  synchronized from verified provider claims at login.
- EC2 instance root volumes are encrypted but disposable. Backing them up can
  create stale app images and secret-bearing snapshots; prefer rebuild from
  Terraform/ECR/SSM unless a concrete irreplaceable host asset is identified.
- Terraform state, tfvars, backend configs, and plan files have different
  contracts. State recovery must not weaken the plan-artifact hygiene or
  no-live-cloud-identifier guardrails.
- Alerting on "backup failure" may require event sources rather than metrics
  for some AWS services. Keep the event source explicit instead of inventing a
  synthetic health check that cannot observe the actual backup service.

## Anti-Patterns

- Adding an app-level "DR service" or Django model to track cloud backups when
  Terraform/AWS service events/runbook evidence are the natural ownership
  boundary.
- Duplicating object-storage, OIDC/Cognito, audit, upload-validation, secret,
  or exception schemas in a DR script.
- Treating portal uploads, log archives, engine state, Terraform state, and
  RDS snapshots as one S3 durability class.
- Broadening EC2 IAM, KMS decrypt, S3, or Secrets Manager permissions to make
  recovery tests easier.
- Logging Cognito user exports, raw email lists, signed URLs, S3 object keys at
  high cardinality, DB endpoints, secret ARNs, or Terraform state contents.
- Silencing Checkov/TFLint/ADR guard to add backup resources quickly.
- Publishing RTO/RPO targets that are not backed by a concrete restore
  primitive and a test record.

## Non-Goals

- No implementation of the runbook, restore scripts, Terraform resources,
  alarms, replication, or backup jobs in this preflight.
- No new cloud abstraction, persistence schema, exception hierarchy, logging
  framework, metrics framework, or workflow engine.
- No redesign of Django authentication, OIDC/Identity Platform, CMS/CTF upload
  flows, queue envelopes, worker processing, Guacamole session handling, or
  range provisioning.
- No migration of Terraform backends, state keys, provider versions, or
  bootstrap ownership unless the implementation explicitly scopes state DR.
- No change to GCP/Kubernetes disaster recovery posture for this AWS issue.

## Validation Expectations

For docs-only follow-up changes, run targeted ADR guard on touched files. If
the implementation changes Terraform, workflows, Kubernetes, or
`shifter/shifter_platform`, also run the repo-required stack checks from
`.gc/plan-rules.md` and `AGENTS.md` for the touched surfaces.

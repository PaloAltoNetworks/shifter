# Disaster Recovery Runbook — AWS Portal Stack

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/160>
Design note: [`docs/architecture/aws-disaster-recovery-preflight-160.md`](../architecture/aws-disaster-recovery-preflight-160.md)
Region: `us-east-2` (all portal resources)

This runbook is the operator procedure for recovering portal data and
infrastructure after a destructive failure (accidental delete, corruption,
region/AZ outage, failed deploy). It covers the AWS portal stack only — RDS,
the portal upload bucket, portal EC2/ASG runtime, Cognito, Terraform state, and
engine/Pulumi state. GCP and Kubernetes DR are out of scope.

## How to read this runbook

Three concepts are kept distinct on purpose — conflating them produces a DR plan
that looks complete but cannot restore data:

- **Availability** controls (Multi-AZ, ASG replacement, health checks) reduce
  downtime from a *single* failure. They are not a tested restore and do not
  protect against delete/corruption that propagates to the standby.
- **Recoverability** controls (backups, snapshots, object versions, identity
  exports) are what you restore *from*. These are the DR primitives.
- **Evidence** is a dated record that a restore primitive was actually
  exercised and met its target. An untested backup is an assumption, not a
  control. See [Tested recovery exercise](#tested-recovery-exercise).

Data classes drive the target. **Authoritative** state (RDS) must be restorable
with a bounded RPO. **Generated** state (EC2 root volumes, Redis, range compute)
is rebuilt, not restored. **Ephemeral** state (portal uploads) is accepted-loss
by design. **Identity-provider** state (Cognito) is reseeded, not restored into
the app database. **Infrastructure state** (Terraform/Pulumi) is recovered from
object versions.

## Component recovery matrix

| Component | Data class | Owner surface | RTO | RPO | Restore primitive | Alert source | Region policy |
|---|---|---|---|---|---|---|---|
| Portal RDS (PostgreSQL) | Authoritative | `modules/portal/rds`, env `db_*` vars | ≤ 2 h (drill: ~53 min) | ~5–10 min (PITR log lag) | PITR or snapshot restore to new instance | RDS event subscription (`backup`/`failure`/`low storage`) → backup-alerts SNS | Same-region; Multi-AZ in prod/proof. Cross-region copy deferred (see [Deferred](#deferred-enhancements)) |
| Guacamole RDS (PostgreSQL) | Authoritative (session/connection metadata) | `modules/guacamole/rds.tf`, env `guacamole_db_*` vars | ≤ 2 h | ~5–10 min (PITR log lag) | PITR or snapshot restore to new instance | RDS event subscription → backup-alerts SNS | Same-region; Multi-AZ in prod/proof |
| Portal uploads (S3) | Ephemeral | `modules/portal/s3` | n/a | Accepted loss | None — rebuild on re-upload | n/a | Same-region. Versioning/CRR intentionally off (see [S3 uploads](#portal-uploads-s3)) |
| Portal EC2 / ASG | Generated | `modules/portal/ec2`, `scripts/portal-deploy/deploy_portal.sh` | ≤ 1 h | n/a (stateless) | Terraform apply + ASG instance refresh + SSM redeploy | ASG/worker-health alarms (existing) | Same-region, multi-AZ ASG |
| Cognito user pool | Identity-provider | `modules/portal/cognito` | ≤ 4 h | Best-effort (export cadence) | Terraform recreate pool + reseed users; Django users restore via RDS | Pool deletion protection (prod) | Same-region; managed service |
| Terraform state (S3 backend) | Infrastructure | `scripts/bootstrap/terraform_backend.py`, `render_aws_backend_configs.py` | ≤ 1 h | ≤ last apply | S3 object-version restore; cross-region copy of state bucket | S3 bucket versioning | Same-region; cross-region copy is an operator step |
| Engine/Pulumi state (S3 + DynamoDB) | Infrastructure | `modules/engine-state` | ≤ 1 h | ≤ last stack op | S3 noncurrent-version restore; DynamoDB PITR for locks | DynamoDB PITR | Same-region |
| Secrets Manager | Authoritative (credentials) | `modules/portal/rds`, `modules/guacamole`, `modules/portal/ssm` | ≤ 30 min | n/a (regenerated) | Terraform regenerates from `random_password`; rotate consumers | n/a | Same-region |
| Redis (channel layer) | Generated | `modules/portal/redis` | ≤ 30 min | n/a (ephemeral) | Recreate replication group; clients reconnect | Existing Redis alarms | Same-region |
| Range compute/state | Generated | engine provisioner, Pulumi state | ≤ 1 h per range | n/a | Re-provision from scenario template + engine/Pulumi state | Range launch-failure alarm | Same-region |

RTO/RPO are **targets**, not guarantees. The portal-RDS row is backed by a real
PITR drill (see [Tested recovery exercise](#tested-recovery-exercise) — 2026-06-24:
~53 min RTO, ~7 min RPO on dev); the RPO is bounded by RDS transaction-log
shipping, so confirm the instance's *latest restorable time* during an incident
rather than assuming it. The other rows are design targets whose evidence log is
still to be filled — a target is only fully credible once that component's drill
has run.

## Per-component recovery procedures

### Portal RDS (PostgreSQL)

The portal database is the authoritative application store (Django
`auth_user`, `UserProfile`, audit trail, CMS/CTF/range metadata). Automated
backups are enabled (`backup_retention_days = 7` in all environments),
`copy_tags_to_snapshot = true`, and a final snapshot is taken on delete except
where `db_skip_final_snapshot = true` (dev/proof).

RDS restores never overwrite the source instance — they create a **new**
instance. Recovery is therefore: restore to a new identifier, validate, then
repoint the application by updating the DB host (Secrets Manager + SSM) or by
renaming.

**Point-in-time recovery (preferred — bounded RPO):**

```sh
# 1. Confirm the window actually available right now.
aws --region us-east-2 rds describe-db-instances \
  --db-instance-identifier <name_prefix>-db \
  --query 'DBInstances[0].LatestRestorableTime'

# 2. Restore to a new instance at the chosen timestamp.
aws --region us-east-2 rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier <name_prefix>-db \
  --target-db-instance-identifier <name_prefix>-db-restore \
  --restore-time 2026-06-24T12:00:00Z \
  --db-subnet-group-name <name_prefix>-db-subnet \
  --no-publicly-accessible

# 3. Wait until available, then validate row counts / latest audit timestamp
#    against the expected pre-incident state before any cutover.
aws --region us-east-2 rds wait db-instance-available \
  --db-instance-identifier <name_prefix>-db-restore
```

**Snapshot restore (when PITR window has aged out):** use
`restore-db-instance-from-db-snapshot` with the latest automated or the final
snapshot (`<name_prefix>-db-final`). Same new-instance-then-cutover flow.

**Cutover:** the application reads the DB host from the
`shifter-<name_prefix>-db-credentials` Secrets Manager secret. After validating
the restored instance, update that secret's `host` to the restored endpoint and
redeploy (SSM) so workers reconnect, OR delete the corrupted instance and rename
the restored one to the original identifier. Prefer the secret-update path in
prod so you keep the corrupted instance for forensics.

### Guacamole RDS (PostgreSQL)

Same primitives and flow as portal RDS, against `<name_prefix>-guacamole-db` and
the `shifter-<name_prefix>-guacamole-db` secret. Guacamole stores connection
definitions and session/recording metadata — authoritative for Guacamole, but
distinct from the portal DB. A portal DB recovery does **not** recover Guacamole;
run both if both were affected.

### Portal uploads (S3)

Classified **ephemeral** by design — authoritative state lives in RDS, so the
upload bucket has versioning and cross-region replication intentionally disabled
(see [`docs/architecture/s3-bucket-hardening-preflight.md`](../architecture/s3-bucket-hardening-preflight.md)
and #143/#219). There is no restore primitive: lost upload objects are
re-uploaded by users/agents. Do **not** silently flip this bucket to durable to
make a generic checklist pass — that changes delete/retention semantics for
every consumer (agent uploads, experiment scripts, CTF attachments) and requires
revisiting lifecycle, KMS, and ADR exceptions as its own design decision.

### Portal EC2 / ASG

Portal and AgentChat instances are **generated** runtime — no application state
lives on the root volume. Recovery is rebuild, not restore:

1. `terraform apply` the portal stack to recreate launch templates / ASG.
2. Trigger an ASG **instance refresh** (or scale the ASG to replace instances).
   New instances run `user_data.sh`, hydrate config/secrets from SSM + Secrets
   Manager, pull the pinned ECR image, and register with the ALB.
3. Verify the worker-health and ALB target health are green.

Do not back up EC2 root volumes as application state — that produces stale app
images and secret-bearing snapshots. AMI backups are only justified for a
prebaked, irreplaceable image, which the portal does not use.

### Cognito

The user pool is Terraform-managed (config recreatable from
`modules/portal/cognito`), but **user identities, MFA enrollment, and group
membership are not in RDS**. Pool deletion protection is on in prod.

- If the pool config is lost but the pool survives: `terraform apply` restores
  configuration (clients, domain, triggers).
- If user *identities* are lost: there is no point-in-time restore. Reseed from
  the last user export (see cadence in [Deferred](#deferred-enhancements)) or
  re-invite. Django `auth_user`/`UserProfile`/groups are restored from RDS and
  are re-synchronized from verified provider claims at next login — so the RDS
  restore covers app-side authorization; the Cognito reseed covers
  authentication identity. Treat these as two separate restores.

### Terraform state (S3 backend)

State lives in an S3 backend (`encrypt = true`, `use_lockfile = true`,
`us-east-2`); bucket/key are injected at `init` via `-backend-config`, rendered
by `scripts/bootstrap/terraform_backend.py` /
`scripts/terraform/render_aws_backend_configs.py`. The state bucket has
versioning enabled.

- **Corrupted/deleted state object:** restore the prior S3 object version of the
  specific `…/terraform.tfstate` key (`aws s3api list-object-versions` →
  `copy-object` the good version back over the key). The `use_lockfile` setting
  means no separate DynamoDB lock to reconcile.
- **Region/bucket loss:** copy the versioned state bucket to a recovery bucket
  (`aws s3 sync` or cross-region `copy-object`) and re-`init` with a
  `-backend-config` pointing at the recovery bucket. Do not commit live backend
  bucket/key names into the repo — keep rendered backend configs in `~/.shifter`
  or CI temp space as the bootstrap script already does.

State may contain generated secret material; treat recovered state files with
the same handling as secrets (no world-readable copies, no CI artifacts).

### Engine / Pulumi state (S3 + DynamoDB)

The engine stores range/stack state in the `<name_prefix>-pulumi-state-<account>`
S3 bucket (versioned, `force_destroy = false`) with a DynamoDB locks table
(`<name_prefix>-pulumi-locks`, PITR enabled) and the `<name_prefix>-pulumi-secrets`
CMK.

- **State object loss:** restore the prior S3 object version (noncurrent
  versions transition to Glacier after the configured window — restore from
  Glacier first if the needed version has aged out).
- **Lock table loss/corruption:** restore via DynamoDB point-in-time recovery to
  a new table, then repoint the engine, or recreate the table (locks are
  transient).
- **Range recovery:** ranges are generated compute. Re-provision from the
  scenario template; the engine reconciles against recovered Pulumi state.

### Secrets Manager

DB and app credentials are generated by Terraform (`random_password`) and stored
in Secrets Manager under the portal CMK. The portal DB credentials secret uses
`recovery_window_in_days = 0` (immediate deletion on destroy, to avoid
name-collision on recreate); Guacamole uses `guacamole_secrets_recovery_window_days`
(7 in prod, 0 in dev). Implication: **there is no recovery window to restore a
deleted secret** — instead `terraform apply` regenerates the secret, after which
consumers must pick up the new value (SSM redeploy / restart). Never print secret
values into logs, argv, state exports, or CI artifacts during recovery.

### Redis (channel layer)

The Django Channels Redis layer is **generated/ephemeral** — no durable state.
Recreate the replication group via Terraform; clients reconnect automatically.
In-flight WebSocket/terminal sessions are lost and re-established by the browser.

## Tested recovery exercise

DR targets are only credible once a real restore has been run end-to-end. The
canonical exercise is an **RDS point-in-time restore-to-new-instance** drill,
which exercises the highest-value authoritative store without touching the live
instance (PITR always restores to a *new* instance).

**Procedure (run against a non-production environment, e.g. dev):**

1. Note a known-good marker in the source DB (e.g. latest `audit` row id +
   timestamp) and the current time `T`.
2. Run the PITR command from [Portal RDS](#portal-rds-postgresql) targeting
   `<name_prefix>-db-drill`, restore-time `T`.
3. Record wall-clock from command start to `db-instance-available` → **observed
   RTO**.
4. Connect to the restored instance, confirm the marker row is present and no
   newer-than-`T` rows exist → **observed RPO** (gap between `T` and latest
   restorable time).
5. Delete the drill instance (`delete-db-instance --skip-final-snapshot`) so the
   exercise leaves no billable resource.
6. Fill the evidence log below.

**Evidence log:**

| Date | Operator | Component | Restore primitive | Observed RTO | Observed RPO | Result | Artifact |
|---|---|---|---|---|---|---|---|
| 2026-06-24 | Platform operator (dev account) | Portal RDS (dev) `dev-portal-db` | PITR (`--use-latest-restorable-time`) → new `dev-portal-db-drill` (db.t3.medium, single-AZ) | ~53 min to `available` (endpoint live ~3 min in; remainder is the post-restore initial automated backup) | ~7 min (source latest-restorable `02:15:17Z` vs restore decision `02:22:07Z`) | PASS — restored instance reached `available`, engine 16.13 / 100 GB / encrypted matching source, with its own restorable window. Validated at infrastructure level; in-DB row-count validation not performed (private endpoint, no in-VPC session wired for the drill). Drill instance deleted (`--skip-final-snapshot --delete-automated-backups`). | AWS RDS event history for `dev-portal-db-drill`; issue #160 thread |

> Notes from the 2026-06-24 run: observed RTO (~53 min) is comfortably within the
> ≤ 2 h target, but most of it is the initial automated backup RDS takes *after*
> the restore — the instance is connectable far earlier (~3 min). In a real
> incident you can begin validation/cutover before the clean `available` signal.
> Observed RPO (~7 min) reflects normal RDS transaction-log shipping lag (latest
> restorable time trails ~5–7 min behind now); treat the ≤ 5 min PITR target as a
> floor and expect a few minutes of lag in practice.
>
> The drill requires AWS access and creates a temporary billable instance. Re-run
> it periodically (and after major schema/engine changes) and append a new row.

## Backup-failure monitoring

Backup and snapshot failures surface as **RDS events**, not CloudWatch metrics,
so detection uses an RDS **event subscription** rather than a synthetic metric.
The `modules/portal/backup-alerts` module (wired in every portal env root)
creates:

- a dedicated customer-managed KMS key whose policy grants the
  `events.rds.amazonaws.com` service principal `kms:GenerateDataKey*` +
  `kms:Decrypt` (account-scoped). This is required because the shared
  `aws_sns_topic.alerts` topic is encrypted with the AWS-managed `alias/aws/sns`
  key, whose policy cannot grant that principal — RDS delivery to it would
  silently fail.
- a CMK-encrypted SNS topic `<name_prefix>-db-backup-alerts` with a topic policy
  allowing the RDS event service to publish, and an email subscription gated on
  `alarm_email`.
- one RDS event subscription covering the portal and Guacamole DB instances,
  categories `availability`, `backup`, `failure`, `low storage`, `maintenance`,
  `recovery`.

**To receive alerts:** set a real `alarm_email` in the environment's
`terraform.tfvars` and confirm the SNS email subscription (AWS sends a
confirmation link on first apply). **To verify delivery** without waiting for a
real failure, publish a test message to the topic
(`aws sns publish --topic-arn <topic-arn> --message "DR alert test"`) and confirm
the email arrives.

## Deferred enhancements

These are evaluated and intentionally **not** implemented now, recorded here so
the decision is explicit rather than an unexamined gap.

- **Cross-region RDS automated-backup replication.** Not enabled. When an
  environment needs cross-region RPO, add
  `aws_db_instance_automated_backups_replication` in the destination region
  (requires a second provider alias for that region, a destination KMS key, and
  `source_db_instance_arn` set to the portal instance), and add a
  `replicate_backups_to_region` variable to gate it per environment. Trigger to
  enable: a stated cross-region RTO/RPO requirement for prod.
- **AMI backups for EC2.** Rejected — instances are stateless/generated and
  rebuilt from Terraform + ECR + SSM. Revisit only if a concrete irreplaceable
  host asset appears.
- **S3 uploads versioning / cross-region replication.** Deferred per #143/#219;
  the bucket is ephemeral by design. Enabling CRR requires versioning, which
  changes delete/retention semantics — a separate design decision, not a DR
  toggle.
- **Cognito scheduled user export.** No automated export cadence today; user
  identity reseed is best-effort. Add a scheduled export job if a bounded
  identity RPO becomes a requirement.

## References

- Design note: [`docs/architecture/aws-disaster-recovery-preflight-160.md`](../architecture/aws-disaster-recovery-preflight-160.md)
- S3 hardening decision: [`docs/architecture/s3-bucket-hardening-preflight.md`](../architecture/s3-bucket-hardening-preflight.md)
- AWS — encrypted SNS for service events: <https://docs.aws.amazon.com/sns/latest/dg/sns-key-management.html>
- AWS — RDS event subscriptions: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_Events.Subscribing.html>

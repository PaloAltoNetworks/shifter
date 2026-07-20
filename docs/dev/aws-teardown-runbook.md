# AWS environment teardown

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

This is the runbook for tearing an AWS environment down to zero: the Terraform
stacks, the resources that block `terraform destroy`, the bootstrap-created
identity and state backend, and the local operator config. It is the reverse of
[`aws-terraform-apply-order.md`](aws-terraform-apply-order.md).

There is no `aws-<env>-destroy.yml` workflow yet (the GCP path has
`gcp-dev-destroy.yml`). Building a repeatable AWS destroy workflow is tracked in
issue #1287; it will be authored from this runbook once the manual sequence is
validated live, so the workflow encodes a proven order rather than a guess. Until
then, teardown is the manual sequence below.

> **Destroys real infrastructure.** Run only against the intended environment.
> Confirm the active AWS profile and account id before every destructive step:
> `aws sts get-caller-identity`.

## Destroy order

Destroy stacks in reverse dependency order: **Portal, then Range, then Core.**
The Portal stack reads Core and Range remote state, so it must go first. Each
stack initializes with its own `-backend-config=<env>.s3.tfbackend`.

## 1. Lift deletion protection (prod, and any env that enabled it)

Several resources ship deletion protection on (secure default in prod; `false`
in dev/proof, so dev/proof usually need no change). For any environment where
these are `true`, set the tfvars to `false` and `terraform apply` the owning
stack first, so the live resource drops protection before destroy:

| Resource | tfvars input | Stack |
|---|---|---|
| Portal RDS | `db_deletion_protection` | Portal |
| Guacamole RDS | `guacamole_db_deletion_protection` | Portal |
| Portal ALB | `enable_deletion_protection` (prod hardcoded `true`) | Portal |
| Portal inspection Network Firewall | `portal_inspection_delete_protection` | Portal |
| Range egress Network Firewall | `network_firewall_delete_protection` | Range |
| Cognito user pool | `deletion_protection` (`ACTIVE`/`INACTIVE`) | Portal |

The prod portal ALB protection is a hardcoded `true` literal
(`environments/prod/portal/main.tf`); flip it to `false` and apply before
destroy.

## 2. Empty the Portal S3 buckets (before the Portal destroy)

No S3 bucket sets `force_destroy`, so a non-empty bucket blocks its stack
destroy. Empty the Portal-owned buckets before the Portal destroy:

- Portal user-storage bucket.
- Log-aggregation `logs` and `alb_access_logs` buckets.
- Engine state bucket (`engine-state` module; `force_destroy = false`).

Empty a versioned bucket by bulk-removing current objects, then sweeping old
versions and delete markers:

```bash
aws s3 rm "s3://$BUCKET" --recursive           # fast bulk of current versions
# then delete remaining versions + delete markers:
aws s3api list-object-versions --bucket "$BUCKET" \
  --query 'Versions[].{Key:Key,VersionId:VersionId}' --output json > /tmp/v.json
aws s3api delete-objects --bucket "$BUCKET" --delete "{\"Objects\": $(cat /tmp/v.json)}"
# repeat for DeleteMarkers[] until both are empty.
```

**Do NOT empty the ECR repos yet.** The guacamole module resolves the `guacd`
and `guacamole-client` image digests through `data "aws_ecr_image"` sources that
are evaluated during the Portal destroy plan. If the repos are empty at that
point, the Portal destroy fails with a data-source lookup error. Empty ECR only
in step 3, after the Portal (and Range) destroys, right before the Core destroy.

## 3. Destroy the stacks

Destroy Portal first, then Range. The Portal stack requires the
`terraform_state_bucket` variable (normally in the CI-rendered remote-state
tfvars); pass it explicitly if you do not have that file locally. Init each
stack against the real state bucket:

```bash
STATE_BUCKET=<the shifter-<env>-infra-<uuid> bucket>
cd platform/terraform/environments/<env>/portal
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve -var="terraform_state_bucket=$STATE_BUCKET"

cd ../range
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve
```

Now empty the four ECR repos (Core stack owns them; prod drops the `<env>-`),
then destroy Core:

```bash
for r in shifter-<env>-portal shifter-<env>-pulumi-provisioner \
         shifter-<env>-guacd shifter-<env>-guacamole-client; do
  aws ecr batch-delete-image --repository-name "$r" \
    --image-ids "$(aws ecr list-images --repository-name "$r" --query 'imageIds[*]' --output json)"
done

cd ../          # environments/<env>/ (Core)
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve
```

If a destroy fails on an unremovable resource (for example a KMS key with
`prevent_destroy`), remove it from state with `terraform state rm` and let the
account-level cleanup handle it, mirroring the KMS handling in
`gcp-dev-destroy.yml`.

### Known destroy stalls and fixes

These recur on a full portal destroy and are safe to resolve directly:

- **Redis rotation Lambda ENI blocks the SG and private subnet.** The portal
  destroy can hang for 20+ minutes on `module.redis.aws_security_group.rotation`
  and `module.vpc.aws_subnet.private[*]` because the redis auth-rotation Lambda's
  VPC ENI is slow to release after the function is deleted. Once the ENI shows
  `Status=available` it is safe to delete manually, which unblocks Terraform's
  next retry:
  ```bash
  aws ec2 describe-network-interfaces \
    --filters Name=description,Values="AWS Lambda VPC ENI-*redis-rotation*" \
    --query 'NetworkInterfaces[?Status==`available`].NetworkInterfaceId' --output text
  aws ec2 delete-network-interface --network-interface-id <eni-id>
  ```
- **Log buckets refill during the destroy.** The ALB access-log and
  log-aggregation buckets keep receiving objects until their writers are
  destroyed, so a bucket you emptied at the start can be non-empty by the time
  Terraform deletes it (`BucketNotEmpty`, HTTP 409). Re-empty those two buckets
  after the writers are gone and re-run the destroy; it then deletes them.
- **`data "aws_ecr_image"` fails when ECR is already empty.** Covered in step 2:
  do not empty the guacamole ECR repos before the Portal destroy. If you already
  did, push any throwaway image tagged with the expected tag (`1.5.5`) to
  `shifter-<env>-guacd` and `shifter-<env>-guacamole-client` so the data sources
  resolve, then destroy.
- **CloudWatch log groups survive the range destroy and block a fresh apply.**
  The range flow-log, Network Firewall, and Route53-resolver log groups
  (`/vpc/<env>-range-flow-logs`, `/aws/network-firewall/<env>-range`,
  `/aws/route53/resolver/<env>-range`) can be recreated by an in-flight log
  delivery that races `terraform destroy`, so they persist after the range
  destroy reports success. Nothing has `skip_destroy`; the fix is a post-destroy
  sweep. A later fresh apply otherwise fails with
  `ResourceAlreadyExistsException`. Delete any that remain:
  ```bash
  for lg in $(aws logs describe-log-groups \
    --query 'logGroups[?contains(logGroupName,`<env>-range`)||contains(logGroupName,`<env>-portal`)||contains(logGroupName,`/vpc/`)].logGroupName' \
    --output text); do aws logs delete-log-group --log-group-name "$lg"; done
  ```

### Broader leftover sweep (resources that block a fresh apply)

**Automated path (preferred).** The bootstrap CLI's `account-recovery` command now
detects (and, with `--sweep`, deletes) most of this leftover set for you, instead of
running the class-by-class `aws` commands below by hand:

```bash
# Read-only detection:
./scripts/bootstrap/deploy.py account-recovery --env "$ENV" --profile <profile>
# Detect and delete the owned leftovers:
./scripts/bootstrap/deploy.py account-recovery --env "$ENV" --profile <profile> --sweep
```

It refuses to run against a live tenant, acts only on resources whose name and
`Project=shifter` / `Environment=<env>` ownership tags both match, never touches
data-bearing resources, and polls asynchronous Network Firewall deletes to
convergence. It covers: AWS Budgets, RDS DB parameter groups, RDS event subscriptions,
EventBridge Scheduler schedules, portal SSM parameters under `/shifter/<env>/portal`,
ECR repositories, KMS aliases, and Network Firewall rule groups. See
`scripts/bootstrap/README.md` for the full safety model.

The classes `account-recovery` does NOT yet automate stay manual below and are marked
_(manual)_: RDS DB subnet groups, the ElastiCache subnet group, EC2 key pairs, and
security groups. Run those after `account-recovery` reports clean.

The env stacks manage every resource below, so a clean `terraform destroy`
removes them. They survive only when a stack destroy is abandoned partway (see
the stalls above) or the `{uuid}` state bucket is deleted before a complete
destroy, which orphans the live resource. A later fresh bootstrap starts from
empty state and collides (`AlreadyExists` / `ResourceAlreadyExistsException`).
This is the #1472 leftover set. Run this sweep after the Portal/Range/Core
destroys report success. Discovery is read-only; delete only what the discovery
lists. Set the environment and account first:

```bash
ENV=<env>                                                   # dev | proof | prod
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

`aws ... --query` uses JMESPath single-quote string literals so the surrounding
double-quoted shell string does not trigger backtick command substitution.

- **AWS Budgets** (`shifter-<env>-s3-cost-alert`, account-scoped, Core stack):
  ```bash
  aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
    --query "Budgets[?starts_with(BudgetName, 'shifter-$ENV-')].BudgetName" --output text
  aws budgets delete-budget --account-id "$ACCOUNT_ID" --budget-name "shifter-$ENV-s3-cost-alert"
  ```
- **RDS DB parameter groups** (`<env>-portal-postgres-pg`, `<env>-portal-guacamole-postgres-pg`):
  ```bash
  aws rds describe-db-parameter-groups \
    --query "DBParameterGroups[?starts_with(DBParameterGroupName, '$ENV-portal')].DBParameterGroupName" --output text
  aws rds delete-db-parameter-group --db-parameter-group-name <name>
  ```
- **RDS DB subnet groups** _(manual)_ (`<env>-portal-db-subnet`, `<env>-portal-guacamole-db-subnet`):
  ```bash
  aws rds describe-db-subnet-groups \
    --query "DBSubnetGroups[?starts_with(DBSubnetGroupName, '$ENV-portal')].DBSubnetGroupName" --output text
  aws rds delete-db-subnet-group --db-subnet-group-name <name>
  ```
- **ElastiCache subnet group** _(manual)_ (`<env>-portal-redis`):
  ```bash
  aws elasticache describe-cache-subnet-groups \
    --query "CacheSubnetGroups[?starts_with(CacheSubnetGroupName, '$ENV-portal')].CacheSubnetGroupName" --output text
  aws elasticache delete-cache-subnet-group --cache-subnet-group-name "$ENV-portal-redis"
  ```
- **EventBridge Scheduler schedules** (`<env>-portal-cognito-rotation-reminder`; the
  dev-box `shifter-dev-box-nightly-shutdown` only if the `global/dev-box` stack was
  applied and you are retiring it):
  ```bash
  aws scheduler list-schedules \
    --query "Schedules[?starts_with(Name, '$ENV-portal')].Name" --output text
  aws scheduler delete-schedule --name <name>
  ```
- **SSM parameters** under `/shifter/<env>/portal` (~38). Enumerate names only; do
  not print values. The range AMI params live under `/shifter/ami/*` and are
  outside this path, so they are preserved:
  ```bash
  aws ssm get-parameters-by-path --path "/shifter/$ENV/portal" --recursive \
    --query 'Parameters[].Name' --output text | tr '\t' '\n' | \
    while read -r p; do [ -n "$p" ] && aws ssm delete-parameter --name "$p"; done
  ```
- **EC2 key pairs** _(manual)_ (`<env>-portal-ctfd-ssh`):
  ```bash
  aws ec2 describe-key-pairs \
    --filters "Name=tag:Project,Values=shifter" "Name=tag:Environment,Values=$ENV" \
    --query "KeyPairs[?starts_with(KeyName, '$ENV-portal')].KeyName" --output text
  aws ec2 delete-key-pair --key-name "$ENV-portal-ctfd-ssh"
  ```
- **RDS event subscriptions** (`<env>-portal-db-backup-events`):
  ```bash
  aws rds describe-event-subscriptions \
    --query "EventSubscriptionsList[?starts_with(CustSubscriptionId, '$ENV-portal')].CustSubscriptionId" --output text
  aws rds delete-event-subscription --subscription-name "$ENV-portal-db-backup-events"
  ```
- **Security groups** _(manual)_ (`<env>-portal*`, tagged `Project=shifter`). A leftover SG
  usually lingers because an ENI still references it (the redis rotation SG stall
  above is the common case); delete it once the ENI is gone. Never delete a VPC
  `default` SG:
  ```bash
  aws ec2 describe-security-groups \
    --filters "Name=tag:Project,Values=shifter" "Name=tag:Environment,Values=$ENV" \
    --query "SecurityGroups[?GroupName!='default' && starts_with(GroupName, '$ENV-portal')].[GroupId,GroupName]" --output text
  aws ec2 delete-security-group --group-id <sg-id>
  ```

## 4. Destroy the runner root and deregister runners

```bash
# Deregister each runner from GitHub first (from the EC2 via SSM):
#   cd /home/ec2-user/actions-runner
#   TOKEN=$(gh api -X POST /repos/Brad-Edwards/shifter/actions/runners/remove-token --jq .token)
#   sudo ./svc.sh stop && sudo ./svc.sh uninstall
#   sudo -u ec2-user ./config.sh remove --token "$TOKEN"
./scripts/runner-deploy.sh --destroy
```

See [`aws-runner-provisioning-runbook.md`](aws-runner-provisioning-runbook.md).

## 5. Destroy the global/iam stack, then the state backend

The `global/iam` stack (applied by bootstrap, not by `deploy.yml`) owns the
GitHub OIDC provider, the `github-actions-shifter-<env>` deploy role, its five
permission policies, and the `shifter-<env>-ci-role-boundary` policy.
`terraform destroy` of the env stacks does not touch any of it. **Destroy
`global/iam` before deleting the state bucket** (the bucket holds its state).
Skipping this is the #1431 failure: a later fresh bootstrap starts from empty
state and collides with these surviving resources (`EntityAlreadyExists` on the
CI boundary policy).

```bash
cd platform/terraform/global/iam
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve -var-file=<env>.tfvars
```

Also delete any stray temporary `github-actions-shifter-<env>-bootstrap` role
(bootstrap normally removes it).

**Then** empty and delete the `{uuid}` state bucket
(`shifter-<env>-infra-<uuid>` for dev/proof, `shifter-infra-<uuid>` for prod).
It is versioned; delete all object versions and delete markers, then the bucket.

## 6. Clear local operator config

```bash
rm -rf ~/.shifter/<env>-<bucket>/
```

## 7. Delete the GitHub environment and its secrets

Delete the environment-scoped and per-env deploy secrets for the environment
being retired (for example `AWS_ROLE_ARN_DEV`, `TF_INFRA_STATE_BUCKET_DEV`,
`TF_VARS_DEV_*`, `SHIFTER_CONFIG_DEV_RANGE`, `SMOKE_*`). Keep shared/prod
secrets (`AWS_ROLE_ARN`, `TF_INFRA_STATE_BUCKET`, `TF_VARS_PROD_PORTAL`,
`SONAR_TOKEN`, `PLATFORM_BOOTSTRAP_STAFF_EMAILS`,
`PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`). See
[`deploy-secrets.md`](deploy-secrets.md) for the full list.

## 8. Verify the account is empty

Confirm no residual EC2, ASG, RDS, ALB, Network Firewall, ECR, IAM
`github-actions-shifter-*` roles, `shifter-<env>-*` policies, OIDC provider,
`<env>-range` / `/vpc/` CloudWatch log groups, or `{uuid}` state bucket remain
before a fresh bootstrap. Also confirm the §3 broader leftover set is gone: the
`shifter-<env>-s3-cost-alert` budget, `<env>-portal*` RDS DB parameter and subnet
groups, the `<env>-portal-redis` ElastiCache subnet group, `<env>-portal*`
EventBridge Scheduler schedules, `/shifter/<env>/portal` SSM parameters,
`<env>-portal*` EC2 key pairs, the `<env>-portal-db-backup-events` RDS event
subscription, and `<env>-portal*` security groups. If any remain, re-run the §3
broader leftover sweep. Preserve only what you intend to reuse (for example range
AMIs and their `/shifter/ami/*` SSM parameters).

# AWS environment teardown

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
permission policies, the `shifter-<env>-ci-role-boundary` policy, **and** the
account-scoped `cursor-bedrock-agent` user (via `cursor-bedrock.tf`).
`terraform destroy` of the env stacks does not touch any of it. **Destroy
`global/iam` before deleting the state bucket** (the bucket holds its state).
Skipping this is the #1431 failure: a later fresh bootstrap starts from empty
state and collides with these surviving resources (`EntityAlreadyExists` on the
cursor-bedrock user and the CI boundary policy).

```bash
cd platform/terraform/global/iam
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve -var-file=<env>.tfvars
```

Destroying `global/iam` deletes the `cursor-bedrock-agent` user and rotates its
access key; a fresh bootstrap recreates both. If you need that account-scoped
tooling preserved across teardowns, keep it out of `global/iam` (tracked in
#1437). Also delete any stray temporary `github-actions-shifter-<env>-bootstrap`
role (bootstrap normally removes it).

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
`github-actions-shifter-*` roles, `shifter-<env>-*` policies,
`cursor-bedrock-agent` user, OIDC provider, `<env>-range` / `/vpc/` CloudWatch
log groups, or `{uuid}` state bucket remain before a fresh bootstrap. Preserve
only what you intend to reuse (for example range AMIs and their `/shifter/ami/*`
SSM parameters).

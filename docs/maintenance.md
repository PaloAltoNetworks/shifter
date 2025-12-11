# Maintenance Windows

Reference for scheduled maintenance windows across Shifter infrastructure.

## RDS (PostgreSQL)

| Resource | Maintenance Window | Backup Window |
|----------|-------------------|---------------|
| prod-portal-db | Monday 04:00-05:00 UTC | 03:00-04:00 UTC |

**Note:** RDS modifications without `apply_immediately` will be queued until the maintenance window. For urgent changes, use AWS CLI:

```bash
aws rds modify-db-instance \
  --db-instance-identifier prod-portal-db \
  --apply-immediately \
  --region us-east-2 \
  --profile dev-workstation-user \
  <other-options>
```

## EC2

Portal EC2 instances have no scheduled maintenance window. Updates are applied via SSM during deployments.

## Checking Pending Modifications

To see if RDS has pending changes waiting for the maintenance window:

```bash
aws rds describe-db-instances \
  --db-instance-identifier prod-portal-db \
  --region us-east-2 \
  --profile dev-workstation-user \
  --query "DBInstances[0].PendingModifiedValues"
```

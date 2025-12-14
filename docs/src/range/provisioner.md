# Provisioner Architecture

This document describes how Shifter provisions and tears down user ranges.

## Overview

The provisioner creates AWS infrastructure (subnets, VMs, containers) when a user launches a range, and cleans it up when they're done. RDS is the single source of truth for all state.

## Architecture

```
Portal VPC (10.0.0.0/16)
├── ALB (public)
├── EC2 (Django Portal)
├── RDS (PostgreSQL) ◄────────────┐
│                                 │
├── Step Functions                │
│   └── Lambda functions ─────────┘
│       ├── create_subnet
│       ├── create_victim
│       ├── create_kali
│       ├── mark_ready
│       └── cleanup
│
└── (Lambda creates resources in Range VPC via AWS APIs)

Range VPC (10.1.0.0/16)
├── Per-user subnets (10.1.{subnet_index}.0/24)
├── Kali EC2 instances (pre-baked AMI)
└── Victim EC2 instances (XDR agent installed)

Chat UI runs in Portal VPC (shared, multi-tenant)
```

## Key Principles

1. **RDS is the source of truth** - All state lives in the database. Both Portal and Lambda read/write to it.

2. **No callbacks or webhooks** - Lambda writes directly to RDS. No HTTP endpoints, no message queues, no cross-service communication.

3. **Lambda in Portal VPC** - The provisioner Lambda functions run in Portal VPC so they can access RDS directly. They create resources in Range VPC via AWS APIs (no VPC peering needed for API calls).

4. **Portal triggers, Lambda executes** - Portal starts Step Functions execution with just `range_id`. Lambda reads everything else from RDS.

5. **Idempotent operations** - Each step checks RDS before acting. If a resource already exists, skip creation. Safe to retry.

## Data Flow

### Provisioning

```
1. User clicks "Launch Range"
   └── Portal: Range.objects.create(status='provisioning')
   └── Portal: stepfunctions.start_execution(range_id)

2. Step Functions executes
   └── Lambda: Read Range from RDS
   └── Lambda: Create subnet in Range VPC
   └── Lambda: UPDATE Range SET subnet_id=X, subnet_cidr=Y
   └── Lambda: Create Kali EC2
   └── Lambda: UPDATE Range SET kali_ip=X, kali_instance_id=Y
   └── Lambda: Create Victim EC2
   └── Lambda: UPDATE Range SET victim_ip=X, victim_instance_id=Y
   └── Lambda: UPDATE Range SET status='ready', ready_at=now()

3. User sees "Ready" on dashboard
   └── Portal: Polls Range.status from RDS
```

### Teardown

```
1. User clicks "Destroy Range"
   └── Portal: Range.status = 'destroying'
   └── Portal: stepfunctions.start_execution(range_id, action='teardown')

2. Step Functions executes
   └── Lambda: Read Range from RDS (get resource IDs)
   └── Lambda: Terminate Kali EC2
   └── Lambda: UPDATE Range SET kali_instance_id=NULL
   └── Lambda: Terminate Victim EC2
   └── Lambda: UPDATE Range SET victim_instance_id=NULL
   └── Lambda: Delete subnet
   └── Lambda: UPDATE Range SET subnet_id=NULL, status='destroyed', destroyed_at=now()

3. User sees "Destroyed" on dashboard
```

## Step Functions State Machine

### Provision Range

```
┌─────────────────┐
│  CreateSubnet   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   CreateKali    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  CreateVictim   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   MarkReady     │
└─────────────────┘

On any error:
         │
         ▼
┌─────────────────┐
│    Cleanup      │──► Delete any created resources
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   MarkFailed    │
└─────────────────┘
```

### Teardown Range

```
┌─────────────────┐
│  TerminateKali  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│TerminateVictim  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  DeleteSubnet   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MarkDestroyed  │
└─────────────────┘
```

## Lambda Functions

All Lambdas:
- Run in Portal VPC (private subnets)
- Have RDS access via security group
- Use IAM Database Authentication (no stored passwords)
- Are idempotent (safe to retry)

### create_subnet

**Input:** `{ range_id }`

**Actions:**
1. Read Range from RDS to get `subnet_index`
2. Calculate CIDR: `10.1.{subnet_index}.0/24`
3. Create subnet in Range VPC
4. Associate with route table
5. Update Range: `subnet_id`, `subnet_cidr`

### create_victim

**Input:** `{ range_id }`

**Actions:**
1. Read Range from RDS to get `subnet_id`, `agent.s3_key`
2. Launch EC2 in the subnet
3. Install XDR agent from S3
4. Update Range: `victim_ip`, `victim_instance_id`

### create_kali

**Input:** `{ range_id }`

**Actions:**
1. Read Range from RDS to get `subnet_id`
2. Launch Kali EC2 from pre-baked AMI
3. Update Range: `kali_ip`, `kali_instance_id`

### mark_ready

**Input:** `{ range_id }`

**Actions:**
1. Update Range: `status='ready'`, `ready_at=now()`

### cleanup

**Input:** `{ range_id }`

**Actions:**
1. Read Range from RDS to get all resource IDs
2. Delete any resources that exist (idempotent)
3. Update Range: clear resource fields, set `status='failed'`

## Timeout Handling

**Problem:** What if provisioning gets stuck?

**Solution:** Background cleanup job

```python
# Run every 5 minutes via cron/CloudWatch Events
def cleanup_stale_ranges():
    stale = Range.objects.filter(
        status='provisioning',
        created_at__lt=timezone.now() - timedelta(minutes=30)
    )
    for range in stale:
        range.status = 'failed'
        range.error_message = 'Provisioning timed out'
        range.save()
        # Trigger cleanup Step Function
        start_cleanup(range.id)
```

## Infrastructure Requirements

### Portal VPC

Lambda functions need:
- Private subnets with NAT Gateway (for AWS API calls)
- Security group allowing RDS access
- VPC endpoints (optional, for cost savings):
  - `com.amazonaws.{region}.ec2`
  - `com.amazonaws.{region}.secretsmanager`

### Range VPC

No special requirements. Lambda creates resources here via AWS APIs (not network calls).

### IAM

Lambda role needs:
- EC2: CreateSubnet, DeleteSubnet, RunInstances, TerminateInstances, etc.
- RDS: `rds-db:connect` (for IAM Database Authentication)
- RDS: Network access (via security group)
- S3: GetObject (for agent installers)

## Local Development

For local dev, the stub provisioner simulates this flow:

```python
def start_provisioning(range_id):
    # In production: start Step Functions
    # In local dev: background thread that updates RDS directly
    thread = threading.Thread(target=_stub_provision, args=(range_id,))
    thread.start()

def _stub_provision(range_id):
    time.sleep(3)  # Simulate work
    range = Range.objects.get(id=range_id)
    range.status = 'ready'
    range.victim_ip = '10.0.1.100'  # Fake
    range.chat_url = f'http://localhost:3000/range-{range_id}'
    range.save()
```

## Security Considerations

### 1. Lambda IAM - Scoped to Range VPC Only

**Risk:** Lambda with broad EC2 permissions could affect Portal infrastructure.

**Mitigations:**
```hcl
# Lambda can ONLY operate on Range VPC resources
resource "aws_iam_policy" "provisioner_lambda" {
  policy = jsonencode({
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ec2:CreateSubnet", "ec2:DeleteSubnet", ...]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:Vpc" = var.range_vpc_id  # Range VPC only
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:RunInstances", "ec2:TerminateInstances"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:Vpc" = var.range_vpc_id
            "aws:RequestTag/shifter:range_id" = "*"  # Must be tagged
          }
        }
      }
    ]
  })
}
```

### 2. Database Access - Minimal Permissions

**Risk:** Lambda could read/modify any database table.

**Mitigations:**
- Dedicated DB user for Lambda (not the Django app user)
- Permissions limited to `mission_control_range` table only
- Only UPDATE on specific columns (no DELETE, no schema changes)
- IAM Database Authentication (no passwords to manage or rotate)

```sql
-- Lambda DB user permissions (created via Django migration for simplicity)
-- IAM auth eliminates password management - Lambda uses generate_db_auth_token()
CREATE USER provisioner_lambda;
GRANT rds_iam TO provisioner_lambda;
GRANT CONNECT ON DATABASE shifter TO provisioner_lambda;
GRANT USAGE ON SCHEMA public TO provisioner_lambda;
GRANT SELECT ON mission_control_range TO provisioner_lambda;
GRANT SELECT ON mission_control_agentconfig TO provisioner_lambda;
GRANT UPDATE (status, subnet_id, subnet_cidr, victim_ip, victim_instance_id,
              chat_url, error_message, ready_at, destroyed_at)
ON mission_control_range TO provisioner_lambda;
-- No INSERT, DELETE, or access to other tables
```

### 3. Range Isolation

**Risk:** User ranges could attack each other or Portal.

**Mitigations:**
- Each range gets dedicated subnet with security group
- Default deny between subnets (no inter-range traffic)
- Range VPC has NO route to Portal VPC
- Victim VMs have no IAM role (can't call AWS APIs)
- Outbound traffic logged via VPC Flow Logs

### 4. Input Validation

**Risk:** Malicious `range_id` could trick Lambda.

**Mitigations:**
- Lambda validates range exists before acting
- Lambda checks range belongs to expected status (state machine)
- Step Functions execution name includes `range_id` for audit
- All operations logged to CloudWatch with range context

### 5. Resource Tagging

All provisioned resources MUST be tagged:

```python
tags = {
    "shifter:range_id": str(range_id),
    "shifter:user_id": str(user_id),
    "shifter:created_at": timestamp,
    "Project": "shifter",
    "Environment": "prod",
    "ManagedBy": "provisioner-lambda"
}
```

This enables:
- Audit trail (who created what, when)
- Cost allocation per user
- Cleanup of orphaned resources
- IAM conditions (Lambda can only affect tagged resources)

### 6. Secrets Management

| Secret | Storage | Rotation | Access |
|--------|---------|----------|--------|
| DB credentials (Lambda) | IAM DB Auth | N/A (token-based) | Lambda IAM role only |
| DB credentials (Portal) | Secrets Manager | 30 days | EC2 IAM role only |
| Django SECRET_KEY | Secrets Manager | Manual | EC2 IAM role only |

**Note:** Lambda uses IAM Database Authentication instead of stored passwords. The PostgreSQL user is created via Django migration (runs on deploy), eliminating the need for a separate secrets management Lambda or manual user creation.

### 7. Network Security

```
Portal VPC (10.0.0.0/16)
├── Public subnet: ALB only
├── Private subnet: EC2, RDS, Lambda
└── No route to Range VPC

Range VPC (10.1.0.0/16)
├── Per-range subnets: Victim, Kali
├── Internet Gateway: For XDR agent connectivity
└── No route to Portal VPC
```

Lambda creates resources in Range VPC via **AWS APIs** (not network traffic). No VPC peering needed.

### 8. Monitoring & Alerts

CloudWatch alarms for:
- Step Functions execution failures
- Lambda errors
- Ranges stuck in `provisioning` > 30 minutes
- Unusual EC2 instance launches
- Database connection failures

## Future Enhancements

1. **Progress tracking** - Add `provisioning_step` field to show which step is running
2. **Retry logic** - Step Functions built-in retry with exponential backoff
3. **Parallel steps** - Create victim and Kali in parallel (after subnet exists)
4. **Cost optimization** - Auto-destroy ranges after N hours of inactivity

# Pulumi Provisioner

ECS Fargate task that provisions and destroys range infrastructure using Pulumi.

## How It Works

```mermaid
sequenceDiagram
    participant Portal
    participant ECS
    participant Pulumi
    participant RDS
    participant AWS
    participant SSM

    Portal->>ECS: run_task(provision, range_id)
    ECS->>Pulumi: python main.py provision --range-id N
    Pulumi->>RDS: status = provisioning
    Pulumi->>AWS: Create subnet, EC2s, secrets
    alt DC Present
        Pulumi->>SSM: Wait for agent online
        Pulumi->>SSM: Install AD DS feature
        Pulumi->>SSM: Reboot, wait for instance
        Pulumi->>SSM: Promote to DC
        Pulumi->>SSM: Verify AD DS running
    end
    Pulumi->>RDS: status = ready, IPs, ARNs
```

## Container Structure

```
pulumi-provisioner/
├── main.py              # Container entrypoint
├── __main__.py          # Pulumi program entry
├── config.py            # Config from env + DB
├── components/
│   ├── network.py       # Subnet creation
│   ├── instance.py      # EC2 + SSH key secrets
│   ├── range_stack.py   # Composes network + instances
│   ├── ssm_executor.py  # Generic SSM command runner
│   ├── setup_orchestrator.py  # Executes setup plans
│   └── plans/
│       └── dc_setup.py  # DC-specific setup steps
└── templates/           # Bootstrap user data (Jinja2)
```

## Operations

**Provision** (`python main.py provision --range-id N`):
1. Connect to RDS via IAM auth
2. Update status → `provisioning`
3. Create/select Pulumi stack `range-{id}`
4. Set stack config from env vars
5. Run `pulumi up`
6. Read outputs (subnet_id, IPs, SSH key ARNs)
7. Update status → `ready` with resource details

**Destroy** (`python main.py destroy --range-id N`):
1. Update status → `destroying`
2. Run `pulumi destroy`
3. Remove Pulumi stack
4. Update status → `destroyed`

## What Gets Created

Per range:
- Subnet (/24 in Range VPC)
- Kali EC2 (from pre-baked AMI)
- Victim EC2 (from pre-baked AMI)
- DC EC2 (optional, Windows Server with AD DS)
- SSH keys in Secrets Manager (per instance)
- SSM Parameter for DC config (when DC present)

## DC Setup via SSM

DC instances require multi-step setup that cannot run in user data (reboots required). Setup uses SSM Run Command orchestration:

1. **Instance Creation** - EC2 created with bootstrap-only user data (hostname, SSH)
2. **Agent Wait** - Provisioner polls until SSM agent reports online
3. **AD DS Install** - `Install-WindowsFeature AD-Domain-Services` via SSM
4. **Reboot** - Instance reboots, provisioner waits for it to return
5. **DC Promotion** - `Install-ADDSForest` via SSM
6. **Verification** - Confirm AD DS service running

If any step fails, the Pulumi stack fails and resources are cleaned up.

**Why SSM instead of user data:**
- User data runs fire-and-forget with no visibility
- AD DS install requires reboot before promotion
- SSM provides exit codes and output for each step
- Failures become Pulumi errors, triggering stack rollback

Domain member victims use user data with retry logic to join the domain once DC is ready.

## State Backend

- **S3**: State files (`s3://{prefix}-pulumi-state`)
- **DynamoDB**: Locking (`{prefix}-pulumi-locks`)
- **KMS**: Secrets encryption (dedicated CMK)

## Config Flow

Environment vars (set by Terraform in ECS task definition):

| Var | Purpose |
|-----|---------|
| `RANGE_VPC_ID` | VPC for range subnets |
| `RANGE_VPC_CIDR` | CIDR for subnet calculation |
| `KALI_AMI_ID` | Pre-baked Kali AMI |
| `VICTIM_AMI_ID` | Pre-baked victim AMI |
| `WINDOWS_AMI_ID` | Windows Server AMI (victims and DC) |
| `AGENT_S3_BUCKET` | Bucket for XDR agent installers |
| `DB_HOST`, `DB_NAME`, `DB_USER` | RDS connection |
| `PULUMI_BACKEND_URL` | S3 state backend |
| `PULUMI_SECRETS_PROVIDER` | KMS key for secrets |

## Database Access

Provisioner connects to RDS using IAM Database Authentication:
- No static credentials
- Uses `provisioner_lambda` DB user
- Generates auth token via `rds.generate_db_auth_token()`

## Trigger

Portal calls `start_provisioning(range_id)` which runs:

```python
ecs.run_task(
    cluster=cluster_arn,
    taskDefinition=task_definition_arn,
    overrides={
        "containerOverrides": [{
            "name": "pulumi-provisioner",
            "command": ["provision", "--range-id", str(range_id)],
        }]
    },
)
```

## Error Handling

- On failure: status → `failed`, error_message saved
- In prod: auto-cleanup on provision failure (`pulumi destroy`)
- Errors logged to CloudWatch

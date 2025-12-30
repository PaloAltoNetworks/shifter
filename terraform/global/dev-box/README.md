# Dev Box

Windows Server 2022 development instance for Shifter development work. Uses a spot instance for cost savings with automatic nightly shutdown.

## Prerequisites

- AWS CLI installed and configured
- AWS profile set: `export AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE`
- Session Manager plugin installed: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

## Deployment

This module is **manually managed** (not part of CI/CD):

```bash
cd terraform/global/dev-box
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform init
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply
```

## Quick Start

Use the management script from the repo root:

```bash
# Check status
./scripts/dev-box.sh status

# Start the dev box
./scripts/dev-box.sh start

# Connect via Fleet Manager (browser-based RDP)
./scripts/dev-box.sh connect

# Get admin password
./scripts/dev-box.sh password

# Start RDP tunnel for local client
./scripts/dev-box.sh tunnel

# Stop when done (saves costs)
./scripts/dev-box.sh stop
```

## Connection Options

### Option 1: SSM Fleet Manager (Recommended)

Browser-based RDP access through AWS Console:

```bash
./scripts/dev-box.sh connect
```

When prompted for credentials:
- Username: `Administrator`
- Password: `./scripts/dev-box.sh password`

### Option 2: SSM Port Forwarding + Local RDP Client

For better performance with a local RDP client:

```bash
# Start tunnel (runs in foreground)
./scripts/dev-box.sh tunnel

# Connect RDP client to localhost:33389
# Use a different port: ./scripts/dev-box.sh tunnel 13389
```

### Option 3: Direct RDP (If Configured)

If you've added your IP to `allowed_rdp_cidrs`:

1. Update `terraform.tfvars`:
   ```hcl
   allowed_rdp_cidrs = ["YOUR.PUBLIC.IP.ADDRESS/32"]
   ```

2. Apply and connect:
   ```bash
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply
   # Connect to public IP shown in output
   ```

## Accessing the Portal Database

### Option A: SSM Port Forwarding (Default Setup)

Use the db-connect script from the repo root:

```bash
# Start port forwarding (runs in foreground)
./scripts/db-connect.sh -e dev

# In another terminal, run queries
./scripts/db-connect.sh -e dev --query "SELECT version()"
```

### Option B: Direct DB Access (Portal VPC)

For direct database access without port forwarding, deploy the dev-box in the portal VPC:

1. Get portal VPC outputs:
   ```bash
   cd terraform/environments/dev/portal
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output vpc_id
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output private_subnet_ids
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output db_security_group_id
   ```

2. Update `terraform.tfvars`:
   ```hcl
   use_portal_vpc              = true
   portal_vpc_id               = "vpc-xxxxxxxxx"        # from step 1
   portal_subnet_id            = "subnet-xxxxxxxxx"     # first private subnet
   portal_db_security_group_id = "sg-xxxxxxxxx"         # from step 1
   ```

3. Apply the changes:
   ```bash
   cd terraform/global/dev-box
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply
   ```

4. Connect directly from the dev-box to RDS using the endpoint.

**Note:** When using portal VPC, the dev-box won't have a public IP. Use SSM Fleet Manager or port forwarding to access it.

## Pre-installed Tools

The dev box comes with:
- Git
- Python 3.12
- Node.js LTS
- AWS CLI
- Terraform
- VS Code
- Google Chrome
- Claude Code (via npm)

## Cost Management

- Uses spot instances for ~70% cost savings
- Automatic shutdown at 11pm Pacific daily
- Root volume persists across spot interruptions

## Terraform Outputs

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output
```

Key outputs:
- `instance_id` - EC2 instance ID
- `ssm_connect_command` - SSM Session Manager command
- `fleet_manager_url` - Browser-based RDP URL
- `admin_password_secret_arn` - Secrets Manager ARN for password

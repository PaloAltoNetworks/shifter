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

## Connecting to the Dev Box

### Option 1: SSM Fleet Manager (Recommended)

Browser-based RDP access through AWS Console:

1. Get the Fleet Manager URL from Terraform output:
   ```bash
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output fleet_manager_url
   ```

2. Open the URL in your browser

3. Click "Connect with Remote Desktop"

4. For the password, retrieve it from Secrets Manager:
   ```bash
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output admin_password_console_url
   ```
   Or via CLI:
   ```bash
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE aws secretsmanager get-secret-value \
     --secret-id shifter-dev-box-admin-password \
     --query SecretString --output text
   ```

### Option 2: SSM Port Forwarding + Local RDP Client

For better performance with a local RDP client:

1. Start the SSM port forwarding session:
   ```bash
   INSTANCE_ID=$(AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output -raw instance_id)
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE aws ssm start-session \
     --target $INSTANCE_ID \
     --document-name AWS-StartPortForwardingSession \
     --parameters '{"portNumber":["3389"],"localPortNumber":["3389"]}'
   ```

2. Connect with your RDP client to `localhost:3389`

3. Login with:
   - Username: `Administrator`
   - Password: (retrieve from Secrets Manager as shown above)

### Option 3: Direct RDP (If Configured)

If you've added your IP to `allowed_rdp_cidrs`:

1. Update `terraform.tfvars`:
   ```hcl
   allowed_rdp_cidrs = ["YOUR.PUBLIC.IP.ADDRESS/32"]
   ```

2. Apply the change:
   ```bash
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply
   ```

3. Connect to the public IP:
   ```bash
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output public_ip
   ```

## Accessing the Portal Database

### Option A: SSM Port Forwarding (Default Setup)

When using the default VPC, connect to RDS via SSM port forwarding through the portal instance:

1. Get the portal EC2 instance ID:
   ```bash
   PORTAL_INSTANCE=$(AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE aws ec2 describe-instances \
     --filters "Name=tag:Name,Values=shifter-dev-portal" "Name=instance-state-name,Values=running" \
     --query 'Reservations[0].Instances[0].InstanceId' --output text)
   ```

2. Start port forwarding to RDS through the portal instance:
   ```bash
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE aws ssm start-session \
     --target $PORTAL_INSTANCE \
     --document-name AWS-StartPortForwardingSessionToRemoteHost \
     --parameters '{"host":["<RDS_ENDPOINT>"],"portNumber":["5432"],"localPortNumber":["5432"]}'
   ```

3. Connect with psql or your preferred client:
   ```bash
   psql -h localhost -p 5432 -U shifter -d shifter
   ```

   (Get credentials from Secrets Manager: `shifter-dev-db-credentials`)

### Option B: Direct DB Access (Portal VPC)

For direct database access without port forwarding, deploy the dev-box in the portal VPC:

1. Get portal VPC outputs:
   ```bash
   cd ../../../environments/dev/portal
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
   cd ../../../global/dev-box
   AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply
   ```

4. Connect directly from the dev-box to RDS using the endpoint:
   ```bash
   psql -h <RDS_ENDPOINT> -p 5432 -U shifter -d shifter
   ```

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

To start the instance after it's been stopped:
```bash
INSTANCE_ID=$(AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output -raw instance_id)
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE aws ec2 start-instances --instance-ids $INSTANCE_ID
```

## Outputs

View all outputs:
```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform output
```

Key outputs:
- `instance_id` - EC2 instance ID
- `ssm_connect_command` - SSM Session Manager command
- `fleet_manager_url` - Browser-based RDP URL
- `admin_password_secret_arn` - Secrets Manager ARN for password

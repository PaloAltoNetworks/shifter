---
name: ngfw-access
description: Connect to NGFW via SSH through the portal instance using SSM. Use when debugging NGFW configuration, checking PAN-OS status, running show commands, or troubleshooting firewall issues.
---

# NGFW SSH Access

Connect to the NGFW appliance via SSH, tunneled through the portal instance using AWS SSM.

## Quick Command

Run PAN-OS commands on the NGFW:

```bash
./scripts/check-ngfw.sh
```

This script automatically:
1. Finds the running NGFW instance
2. Retrieves the SSH key from Secrets Manager
3. Connects via the portal instance using SSM
4. Runs `show system info`

## Manual Connection Method

### Step 1: Find NGFW Instance

```bash
PROFILE="panw-shifter-dev-workstation"
REGION="us-east-2"

aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*ngfw*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].[InstanceId,PrivateIpAddress,KeyName]' \
  --output text
```

### Step 2: Find SSH Key Secret

The SSH key is stored in Secrets Manager. Extract UUID from key name (format: `ngfw-{uuid}`):

```bash
KEY_NAME="ngfw-abc123..."
UUID_PREFIX=${KEY_NAME#ngfw-}

SECRET_ARN=$(aws secretsmanager list-secrets \
  --profile "$PROFILE" \
  --region "$REGION" \
  --output json | jq -r ".SecretList[] | select(.Name | contains(\"ngfw/$UUID_PREFIX\")) | .ARN" | head -1)
```

### Step 3: Get SSH Key

```bash
KEY_CONTENT=$(aws secretsmanager get-secret-value \
  --profile "$PROFILE" \
  --secret-id "$SECRET_ARN" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text)
```

### Step 4: Find Portal Instance

```bash
PORTAL_ID=$(aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*portal*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text)
```

### Step 5: Run Command via SSM

Use SSM to run commands on the portal, which then SSHs to the NGFW:

```bash
aws ssm send-command \
  --profile "$PROFILE" \
  --region "$REGION" \
  --instance-ids "$PORTAL_ID" \
  --document-name AWS-RunShellScript \
  --parameters commands='["echo show system info | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no admin@NGFW_IP"]'
```

## Common PAN-OS Commands

### System Status
```
show system info
show system state
show system resources
```

### Network/Routing
```
show running routing-table ip static-route
show routing route
show interface all
```

### Security Policy
```
show running security-policy
show running nat-policy
```

### Address Objects
```
show running address
show running address-group
```

### Commit Status
```
show jobs all
```

## Architecture Notes

- **NGFW is in a private subnet** - no direct internet access
- **Portal instance acts as bastion** - has SSM agent and can reach NGFW
- **SSH key stored in Secrets Manager** - unique per NGFW instance
- **PAN-OS uses CLI syntax** - commands piped via `echo CMD | ssh admin@IP`

## Troubleshooting

### "Cannot connect to management server"
PAN-OS management plane not ready. Wait and retry - can take 15-25 minutes after boot.

### "Server timeout"
Management plane is starting up. The `poll_for_serial_number()` function in provisioner handles this.

### SSH Connection Refused
NGFW may still be booting. Check instance state and wait for SSH to be available.

## Bootstrap Debugging

### Check Bootstrap Status
```
show system bootstrap status
```

### Bootstrap Logs
The bootstrap configuration log is in configd.log. To see bootstrap-related errors:
```
less mp-log configd.log
```
Then search for "bootstrap" - errors will show which XML nodes are missing or malformed.

Example error indicating missing `<deviceconfig><system>` section:
```
initcfg: devices/entry/deviceconfig/system node does not exist... ignoring bootstrap config
```

### Required bootstrap.xml Structure
The bootstrap.xml must include at minimum:
- `devices/entry[@name='localhost.localdomain']/deviceconfig/system` with hostname
- Any network/interface/zone config goes under `devices/entry[@name='localhost.localdomain']`

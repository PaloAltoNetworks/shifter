# NGFW Debug Guide

How to debug NGFW provisioning: logs, database, and SSH access.

## Prerequisites

- AWS CLI with `panw-shifter-dev-workstation` profile configured
- For DB queries: `./scripts/db-connect.sh -e dev` running in another terminal

---

## ECS Provisioner Logs

The NGFW provisioner runs as an ECS Fargate task.

### Find Running ECS Tasks

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws ecs list-tasks \
  --cluster dev-portal-pulumi \
  --desired-status RUNNING \
  --region us-east-2 \
  --output json
```

### List Recent Log Streams

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws logs describe-log-streams \
  --log-group-name "/ecs/dev-portal-pulumi-provisioner" \
  --region us-east-2 \
  --order-by LastEventTime \
  --descending \
  --limit 5 \
  --query 'logStreams[*].logStreamName' \
  --output table
```

### Get Logs for a Task

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws logs get-log-events \
  --log-group-name "/ecs/dev-portal-pulumi-provisioner" \
  --log-stream-name "pulumi/pulumi-provisioner/TASK_ID" \
  --region us-east-2 \
  --limit 100 \
  --query 'events[*].message' \
  --output text
```

### Filter Logs for Specific Patterns

```bash
# Find SSH-related logs
AWS_PROFILE=panw-shifter-dev-workstation aws logs filter-log-events \
  --log-group-name "/ecs/dev-portal-pulumi-provisioner" \
  --log-stream-names "pulumi/pulumi-provisioner/TASK_ID" \
  --region us-east-2 \
  --filter-pattern "serial" \
  --limit 20 \
  --query 'events[*].message' \
  --output text
```

### Key Log Messages to Look For

- `"Polling for NGFW serial and certificate..."` - SSH polling loop
- `"Serial number not found"` - Bootstrap not complete yet
- `"NGFW verification complete"` - Success!
- `"Authentication (publickey) successful!"` - SSH key auth works
- `"Command completed with exit code 0"` - SSH command executed

---

## Database Queries

Start the DB tunnel first: `./scripts/db-connect.sh -e dev`

### Find NGFW by Name

```sql
-- CMS app (UI-facing)
SELECT id, name, status, created_at, deleted_at
FROM cms_app
WHERE name LIKE '%RogueTwenty%';

-- Engine app (provisioner-facing)
SELECT id, name, status, instance_id, created_at, destroyed_at
FROM engine_app
WHERE name LIKE '%RogueTwenty%';
```

### Find NGFW Request

```sql
SELECT id, user_id, status, created_at, deleted_at
FROM cms_request
WHERE id = 'REQUEST_UUID';
```

### Find Range Instance

```sql
SELECT id, app_id, status, created_at, deleted_at
FROM cms_rangeinstance
WHERE id = INSTANCE_ID;
```

### Check All NGFW-Related Records

```sql
-- Get the full picture for an NGFW
SELECT
  a.name as app_name,
  a.status as cms_status,
  e.status as engine_status,
  e.instance_id as ec2_id,
  r.status as request_status
FROM cms_app a
LEFT JOIN engine_app e ON e.name = a.name
LEFT JOIN cms_request r ON r.id::text = a.id::text
WHERE a.name LIKE '%RogueTwenty%';
```

### Update Status (for cleanup)

```sql
-- Mark as destroyed in CMS
UPDATE cms_app SET status = 'destroyed', deleted_at = NOW() WHERE name = 'NAME';

-- Mark as destroyed in Engine
UPDATE engine_app SET status = 'destroyed', destroyed_at = NOW() WHERE name = 'NAME';

-- Mark request as deleted
UPDATE cms_request SET deleted_at = NOW() WHERE id = 'REQUEST_UUID';
```

---

## Pulumi State

Pulumi state is stored in S3.

### List NGFW Stacks

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws s3 ls \
  s3://dev-range-pulumi-state/.pulumi/stacks/shifter-engine/ \
  --region us-east-2 | grep ngfw
```

### Get Stack Outputs (including SSH key ARN)

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws s3 cp \
  s3://dev-range-pulumi-state/.pulumi/stacks/shifter-engine/ngfw-REQUEST_UUID.json - \
  --region us-east-2 | jq '.checkpoint.latest.resources[] | select(.type == "aws:secretsmanager/secret:Secret") | {urn, id}'
```

---

## SSH into NGFW

## Step 1: Find the NGFW Instance

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws ec2 describe-instances \
  --region us-east-2 \
  --filters "Name=tag:Name,Values=*ngfw*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[*].Instances[*].[InstanceId,PrivateIpAddress,Tags[?Key==`Name`].Value|[0],KeyName]' \
  --output table
```

Note the `PrivateIpAddress` (e.g., `10.1.7.118`) and `KeyName` (e.g., `ngfw-35ebede0`).

## Step 2: Find the SSH Key Secret

The KeyName format is `ngfw-{uuid_prefix}`. Find the full secret:

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws secretsmanager list-secrets \
  --region us-east-2 \
  --query 'SecretList[*].[Name,ARN]' \
  --output table | grep ngfw
```

Look for a secret matching the uuid prefix from KeyName (e.g., `shifter/dev/ngfw/35ebede0-.../ssh-key`).

## Step 3: Get and Base64 Encode the Key

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws secretsmanager get-secret-value \
  --secret-id "arn:aws:secretsmanager:us-east-2:878848911818:secret:shifter/dev/ngfw/YOUR-UUID/ssh-key-SUFFIX" \
  --region us-east-2 \
  --query 'SecretString' \
  --output text | base64 -w0
```

Save the base64 output for the next step.

## Step 4: Find the Portal Instance

The NGFW is in the range VPC's NGFW subnet (10.1.x.x), not directly accessible. SSH via the portal:

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws ec2 describe-instances \
  --region us-east-2 \
  --filters "Name=tag:Name,Values=*portal*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],PrivateIpAddress]' \
  --output table
```

## Step 5: SSH via SSM Send-Command

Use the portal instance ID, base64 key, and NGFW IP:

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws ssm send-command \
  --region us-east-2 \
  --instance-ids PORTAL_INSTANCE_ID \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["echo BASE64_KEY_HERE | base64 -d > /tmp/ngfw.pem && chmod 600 /tmp/ngfw.pem && echo show system info | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@NGFW_IP 2>&1"]' \
  --query 'Command.CommandId' \
  --output text
```

## Step 6: Get the Result

```bash
AWS_PROFILE=panw-shifter-dev-workstation aws ssm get-command-invocation \
  --region us-east-2 \
  --command-id COMMAND_ID \
  --instance-id PORTAL_INSTANCE_ID \
  --query '[Status,StandardOutputContent,StandardErrorContent]' \
  --output json
```

## Example Full Workflow

```bash
# 1. Find NGFW
AWS_PROFILE=panw-shifter-dev-workstation aws ec2 describe-instances --region us-east-2 --filters "Name=tag:Name,Values=*ngfw*" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId,PrivateIpAddress,KeyName]' --output table

# 2. Get key (replace UUID)
KEY_B64=$(AWS_PROFILE=panw-shifter-dev-workstation aws secretsmanager get-secret-value --secret-id "shifter/dev/ngfw/35ebede0-be20-4fc9-aa5e-01ae5ce65304/ssh-key" --region us-east-2 --query 'SecretString' --output text | base64 -w0)

# 3. Find portal
AWS_PROFILE=panw-shifter-dev-workstation aws ec2 describe-instances --region us-east-2 --filters "Name=tag:Name,Values=*portal*" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId,PrivateIpAddress]' --output table

# 4. SSH and run command (replace values)
CMD_ID=$(AWS_PROFILE=panw-shifter-dev-workstation aws ssm send-command --region us-east-2 --instance-ids i-00a57e38f4a7b29ba --document-name AWS-RunShellScript --parameters "commands=[\"echo $KEY_B64 | base64 -d > /tmp/ngfw.pem && chmod 600 /tmp/ngfw.pem && echo show system info | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@10.1.7.118 2>&1\"]" --query 'Command.CommandId' --output text)

# 5. Get result (wait ~15s)
sleep 15 && AWS_PROFILE=panw-shifter-dev-workstation aws ssm get-command-invocation --region us-east-2 --command-id $CMD_ID --instance-id i-00a57e38f4a7b29ba --query '[Status,StandardOutputContent,StandardErrorContent]' --output json
```

## Expected Output

Successful output includes:
- `hostname: ngfw-user-X`
- `serial: 007955XXXXXXXXX`
- `vm-license: VM-SERIES-4`
- `device-certificate-status: Valid`

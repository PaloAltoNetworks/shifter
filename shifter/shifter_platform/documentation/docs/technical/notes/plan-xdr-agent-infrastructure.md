# XDR Agent Deployment on Shifter Infrastructure EC2

## Summary

Deploy XDR agents on Portal EC2 instances at boot time, using a dedicated S3 path for the infrastructure agent installer.

## Scope

- **Target**: Portal EC2 instances only (single instance and ASG modes)
- **Skip**: Pulumi Provisioner (runs on ECS Fargate)
- **Egress**: Use existing open egress (`0.0.0.0/0`) - no network changes needed

## Implementation Steps

### 1. Add XDR Variables to EC2 Module

**File**: `terraform/modules/portal/ec2/variables.tf`

Add new variables at end of file:

```hcl
variable "xdr_agent_s3_path" {
  description = "S3 path to XDR agent installer (e.g., s3://bucket/infrastructure/xdr-agent/installer.sh). Leave empty to skip."
  type        = string
  default     = ""
}

variable "xdr_distribution_id" {
  description = "XDR distribution ID for agent registration (optional)"
  type        = string
  default     = ""
}
```

### 2. Update user_data.sh Template Calls

**File**: `terraform/modules/portal/ec2/main.tf`

Update both `templatefile` calls (single instance ~line 472 and launch template ~line 294) to include:

```hcl
xdr_agent_s3_path   = var.xdr_agent_s3_path
xdr_distribution_id = var.xdr_distribution_id
```

### 3. Add XDR Installation to user_data.sh

**File**: `terraform/modules/portal/ec2/user_data.sh`

Add before final echo statement:

```bash
# ------------------------------------------------------------------------------
# XDR Agent Installation (Optional)
# ------------------------------------------------------------------------------

XDR_AGENT_S3_PATH="${xdr_agent_s3_path}"
XDR_DISTRIBUTION_ID="${xdr_distribution_id}"

install_xdr_agent() {
    if [ -z "$XDR_AGENT_S3_PATH" ]; then
        echo "XDR Agent: Skipping - no S3 path configured"
        return 0
    fi

    echo "XDR Agent: Starting installation..."

    # Check if already installed
    if pgrep -x "traps_daemon" > /dev/null 2>&1 || [ -d "/opt/traps" ]; then
        echo "XDR Agent: Already installed, skipping"
        return 0
    fi

    INSTALLER_DIR=$(mktemp -d)
    INSTALLER_FILE="$INSTALLER_DIR/xdr_installer.sh"

    echo "XDR Agent: Downloading from $XDR_AGENT_S3_PATH"
    if ! aws s3 cp "$XDR_AGENT_S3_PATH" "$INSTALLER_FILE" --region "${aws_region}"; then
        echo "XDR Agent: ERROR - Failed to download installer"
        rm -rf "$INSTALLER_DIR"
        return 1
    fi

    chmod +x "$INSTALLER_FILE"

    INSTALL_CMD="$INSTALLER_FILE"
    if [ -n "$XDR_DISTRIBUTION_ID" ]; then
        INSTALL_CMD="$INSTALL_CMD --distribution-id=$XDR_DISTRIBUTION_ID"
    fi

    if ! $INSTALL_CMD; then
        echo "XDR Agent: ERROR - Installation failed"
        rm -rf "$INSTALLER_DIR"
        return 1
    fi

    rm -rf "$INSTALLER_DIR"
    echo "XDR Agent: Installation complete"
    return 0
}

# Run XDR installation (errors logged but do not fail boot)
if ! install_xdr_agent; then
    echo "XDR Agent: Installation failed - continuing with boot"
fi
```

### 4. Wire Up Environment Variables (Dev)

**File**: `terraform/environments/dev/portal/variables.tf`

Add:

```hcl
variable "xdr_agent_s3_path" {
  description = "S3 path to infrastructure XDR agent installer"
  type        = string
  default     = ""
}

variable "xdr_distribution_id" {
  description = "XDR distribution ID for infrastructure agents"
  type        = string
  default     = ""
}
```

**File**: `terraform/environments/dev/portal/main.tf`

Pass to EC2 module:

```hcl
xdr_agent_s3_path   = var.xdr_agent_s3_path
xdr_distribution_id = var.xdr_distribution_id
```

### 5. Wire Up Environment Variables (Prod)

Same changes as dev in:

- `terraform/environments/prod/portal/variables.tf`
- `terraform/environments/prod/portal/main.tf`

### 6. Configure GitHub Secrets

Add to `TF_VARS_DEV_PORTAL` and `TF_VARS_PROD_PORTAL` secrets:

```hcl
xdr_agent_s3_path   = "s3://shifter-{env}-user-storage-xxxxx/infrastructure/xdr-agent/cortex-xdr-installer.sh"
xdr_distribution_id = "YOUR_DISTRIBUTION_ID"
```

## Pre-deployment: Upload XDR Installer to S3

```bash
aws s3 cp cortex-xdr-installer.sh \
  s3://shifter-dev-user-storage-xxxxx/infrastructure/xdr-agent/cortex-xdr-installer.sh \
  --profile $PANW_SHIFTER_DEV_PROFILE
```

## Files to Modify

| File | Action |
|------|--------|
| `terraform/modules/portal/ec2/variables.tf` | Add 2 new variables |
| `terraform/modules/portal/ec2/main.tf` | Update 2 templatefile calls |
| `terraform/modules/portal/ec2/user_data.sh` | Add XDR installation section |
| `terraform/environments/dev/portal/variables.tf` | Add 2 new variables |
| `terraform/environments/dev/portal/main.tf` | Pass variables to module |
| `terraform/environments/prod/portal/variables.tf` | Add 2 new variables |
| `terraform/environments/prod/portal/main.tf` | Pass variables to module |

## Testing

1. Deploy to dev with XDR config in tfvars
2. For existing instances: Terminate to trigger replacement (user_data runs on new instance)
3. Verify via SSM:

```bash
sudo cat /var/log/cloud-init-output.log | grep "XDR Agent"
ps aux | grep traps
ls -la /opt/traps/
```

## Notes

- XDR installation is optional - empty S3 path skips installation
- Installation failures log errors but don't prevent instance boot
- Existing EC2 role already has S3 access to the user storage bucket
- No network/egress changes needed - Portal VPC allows all outbound traffic

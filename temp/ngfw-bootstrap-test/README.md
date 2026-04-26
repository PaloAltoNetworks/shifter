# NGFW Bootstrap Test

Test environment for validating bootstrap.xml-based NGFW configuration.

## Purpose

Test whether we can pre-configure ethernet1/1, virtual-router, and zone via bootstrap.xml
instead of post-boot SSH commands (which are flaky due to management plane timing issues).

## What Bootstrap.xml Configures

- Admin user with password (default: `admin` / password hash for "admin")
- ethernet1/1 as Layer 3 with DHCP client (no default route)
- ethernet1/1 added to virtual-router "default"
- Zone "ranges" created with ethernet1/1 as member

## Prerequisites

1. AWS CLI configured with `panw-shifter-dev-workstation` profile
2. Terraform installed
3. VM-Series AMI available in us-east-2

## Usage

```bash
cd temp/ngfw-bootstrap-test

# Initialize
terraform init

# Plan (review what will be created)
terraform plan

# Apply (creates resources)
terraform apply

# After ~15-20 minutes for NGFW to boot, test:
# 1. SSH to verify config
ssh -i ngfw-test-key.pem admin@<management_public_ip>

# On the NGFW, verify bootstrap worked:
show interface all
show zone all
show network virtual-router

# 2. Test web UI (should be able to login with admin/admin)
# https://<management_public_ip>

# Cleanup when done
terraform destroy
```

## Generating a Custom Password Hash

The default password is "admin". To use a different password:

```bash
# Generate MD5 hash (PAN-OS format)
openssl passwd -1 -salt shifter yourpassword

# Use the output in terraform.tfvars:
# admin_password_hash = "$1$shifter$..."
```

## Expected Results

After bootstrap completes successfully:

1. `show interface ethernet1/1` should show:
   - Layer3 mode
   - DHCP-assigned IP address

2. `show zone all` should show:
   - Zone "ranges" with ethernet1/1

3. `show network virtual-router` should show:
   - "default" router with ethernet1/1

## If Bootstrap Fails

Check bootstrap status:
```
show system bootstrap status
```

Common issues:
- S3 bucket permissions (IAM role)
- Incorrect folder structure
- XML syntax errors in bootstrap.xml

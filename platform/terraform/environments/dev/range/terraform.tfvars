# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

environment = "dev"
aws_region  = "us-east-2"

tags = {
  Project     = "shifter"
  Environment = "dev"
  ManagedBy   = "terraform"
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

vpc_cidr        = "10.1.0.0/16"
portal_vpc_cidr = "10.0.0.0/16"

# ------------------------------------------------------------------------------
# Phase 5: Additional Log Sources
# ------------------------------------------------------------------------------

enable_flow_logs = true

# ------------------------------------------------------------------------------
# Range Instance IAM
# ------------------------------------------------------------------------------

# Per-deployment value rendered from TF_VARS_DEV_RANGE into local.auto.tfvars.
# Keep the committed baseline account-neutral; apply jobs fail loud when the
# deployment overlay is absent.
agent_s3_bucket = "REPLACE_AGENT_S3_BUCKET"

# ------------------------------------------------------------------------------
# VM-Series NGFW (optional)
# ------------------------------------------------------------------------------

# Regional PAN-OS Marketplace AMI rendered from the deployment overlay.
vm_series_ami_id        = "REPLACE_VM_SERIES_AMI_ID"
vm_series_instance_type = "m5.xlarge"

# ------------------------------------------------------------------------------
# Persistent NGFW Infrastructure
# ------------------------------------------------------------------------------

enable_ngfw_infrastructure = true

# Network Firewall lifecycle
# dev: allow intentional teardown; apply once with this false before destroying
network_firewall_delete_protection = false

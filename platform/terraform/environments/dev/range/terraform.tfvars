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

# Per-account suffix on the user-storage bucket. The dev account is
# 788327019743 (verified via `aws sts get-caller-identity` 2026-05-05).
# The earlier `e3462f0c` suffix was from a previous dev account; the
# `dev-range-range-instance` IAM role's `s3-agent-read` policy was
# pointing at a bucket the current account doesn't own, so any range
# instance trying to fetch from S3 via the instance profile got 403.
# Found while debugging the polaris-vm bake (the bake exemplar uses a
# dedicated `polaris-bake-instance` role to side-step this; production
# range path needs the value here to be right).
agent_s3_bucket = "shifter-dev-user-storage-788327019743"

# ------------------------------------------------------------------------------
# VM-Series NGFW (optional)
# ------------------------------------------------------------------------------

vm_series_ami_id        = "ami-065e27477b191614c" # PAN-OS 11.2.8
vm_series_instance_type = "m5.xlarge"

# ------------------------------------------------------------------------------
# Persistent NGFW Infrastructure
# ------------------------------------------------------------------------------

enable_ngfw_infrastructure = true

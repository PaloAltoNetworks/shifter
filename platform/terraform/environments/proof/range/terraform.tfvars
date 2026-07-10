# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

environment = "proof"
aws_region  = "us-east-2"

tags = {
  Project     = "shifter"
  Environment = "proof"
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

# Per-deployment value rendered from TF_VARS_PROOF_RANGE into local.auto.tfvars.
# Keep the committed baseline account-neutral; apply jobs fail loud when the
# deployment overlay is absent.
agent_s3_bucket = "REPLACE_AGENT_S3_BUCKET"

# ------------------------------------------------------------------------------
# VM-Series NGFW (optional)
# ------------------------------------------------------------------------------

vm_series_ami_id        = "ami-065e27477b191614c" # PAN-OS 11.2.8
vm_series_instance_type = "m5.xlarge"

# ------------------------------------------------------------------------------
# Persistent NGFW Infrastructure
# ------------------------------------------------------------------------------

enable_ngfw_infrastructure = true

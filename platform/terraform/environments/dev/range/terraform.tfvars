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

agent_s3_bucket = "shifter-dev-user-storage-e3462f0c"

# ------------------------------------------------------------------------------
# VM-Series NGFW (optional)
# ------------------------------------------------------------------------------

vm_series_ami_id        = "ami-065e27477b191614c" # PAN-OS 11.2.8
vm_series_instance_type = "m5.xlarge"

# ------------------------------------------------------------------------------
# Persistent NGFW Infrastructure
# ------------------------------------------------------------------------------

enable_ngfw_infrastructure = true

# ------------------------------------------------------------------------------
# OpenBAS Shared Infrastructure
# ------------------------------------------------------------------------------
# Set enable_openbas = true and configure domain to deploy OpenBAS
# Requires DNS validation for ACM certificate

enable_openbas      = false
openbas_domain_name = "openbas.dev.shifter.internal" # Update with actual domain

# ECS sizing (dev defaults - adjust for production)
openbas_task_cpu      = 1024 # 1 vCPU
openbas_task_memory   = 4096 # 4 GB
openbas_desired_count = 2

# Database sizing (dev defaults)
openbas_db_instance_class = "db.t3.small"
openbas_db_multi_az       = true
